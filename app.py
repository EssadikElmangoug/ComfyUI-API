from flask import Flask, request, jsonify, Response, send_file, render_template, redirect, url_for, flash, session
import requests
import json
import time
import os
import logging
from werkzeug.utils import secure_filename
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import string
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = os.urandom(24)  # For session management

# SQLite Configuration
DB_PATH = 'comfyui.db'

def init_db():
    """Initialize the SQLite database"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Create users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_admin BOOLEAN NOT NULL DEFAULT 0
        )
    ''')
    
    # Create api_keys table
    c.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            api_key TEXT UNIQUE NOT NULL,
            created_at REAL NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # This enables column access by name
    return conn

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# ComfyUI API endpoint
COMFYUI_URL = "http://localhost:3000"

# Headers to prevent caching
NO_CACHE_HEADERS = {
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'Pragma': 'no-cache',
    'Expires': '0'
}

def generate_api_key(length=32):
    """Generate a random API key"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def login_required(f):
    """Decorator to require login for certain routes"""
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def api_key_required(f):
    """Decorator to require API key for certain routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('Authorization')
        if not api_key:
            return jsonify({'error': 'API key is required'}), 401
        
        # Remove 'Key ' prefix if present
        if api_key.startswith('Key '):
            api_key = api_key[4:]
        
        # Verify API key exists in database
        conn = get_db()
        key = conn.execute('SELECT * FROM api_keys WHERE api_key = ?', (api_key,)).fetchone()
        conn.close()
        
        if not key:
            return jsonify({'error': 'Invalid API key'}), 401
            
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            return redirect(url_for('admin_dashboard'))
        
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin_dashboard():
    conn = get_db()
    api_keys = conn.execute('SELECT * FROM api_keys').fetchall()
    conn.close()
    return render_template('admin.html', api_keys=api_keys)

@app.route('/admin/generate-api-key', methods=['POST'])
@login_required
def generate_new_api_key():
    name = request.form.get('name')
    if not name:
        flash('Name is required')
        return redirect(url_for('admin_dashboard'))
    
    api_key = generate_api_key()
    conn = get_db()
    conn.execute('INSERT INTO api_keys (name, api_key, created_at) VALUES (?, ?, ?)',
                (name, api_key, time.time()))
    conn.commit()
    conn.close()
    
    flash('API key generated successfully')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete-api-key/<int:key_id>', methods=['POST'])
@login_required
def delete_api_key(key_id):
    try:
        conn = get_db()
        conn.execute('DELETE FROM api_keys WHERE id = ?', (key_id,))
        conn.commit()
        conn.close()
        flash('API key deleted successfully')
    except Exception as e:
        flash('Error deleting API key')
    return redirect(url_for('admin_dashboard'))

# Create initial admin user if none exists
def create_initial_admin():
    conn = get_db()
    user = conn.execute('SELECT * FROM users').fetchone()
    if not user:
        admin_password = generate_api_key(12)  # Generate a random password
        conn.execute('INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)',
                    ('admin', generate_password_hash(admin_password), True))
        conn.commit()
        logger.info(f"Created initial admin user with password: {admin_password}")
    conn.close()

# Initialize database and create admin user
init_db()
create_initial_admin()

# Load workflow templates
def load_workflow(workflow_name):
    try:
        with open(f"{workflow_name}.json", 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Workflow file {workflow_name}.json not found")
        raise
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in {workflow_name}.json")
        raise
    except UnicodeDecodeError as e:
        logger.error(f"Encoding error in {workflow_name}.json: {str(e)}")
        raise

def check_completion_status(prompt_id):
    try:
        response = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", headers=NO_CACHE_HEADERS)
        if response.status_code == 200:
            history = response.json()
            logger.debug(f"ComfyUI history response: {json.dumps(history)}")
            
            if prompt_id in history:
                current_output = history[prompt_id]
                logger.debug(f"Current output for prompt {prompt_id}: {json.dumps(current_output)}")
                
                # Check all possible output locations
                outputs = current_output.get('outputs', {})
                for node_id, node_output in outputs.items():
                    if node_output.get('videos'):
                        logger.info(f"Found video output in node {node_id}")
                        return True, current_output
                    elif node_output.get('images'):
                        logger.info(f"Found image output in node {node_id}")
                        return True, current_output
        return False, None
    except requests.RequestException as e:
        logger.error(f"Error checking completion status: {str(e)}")
        raise

@app.route('/', methods=['GET'])
def home():
    return jsonify({'message': 'Hello, This is the API home page'})

@app.route('/api/flux-text-to-image', methods=['POST'])
@api_key_required
def flux_text_to_image():
    try:
        # Validate request data
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
            
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
            
        prompt = data.get('prompt')
        if not prompt:
            return jsonify({'error': 'prompt is required'}), 400
            
        negative_prompt = ''
        
        # Get width and height with defaults
        width = data.get('width', 1024)
        height = data.get('height', 1024)
        
        # Validate width and height are positive integers
        try:
            width = int(width)
            height = int(height)
            if width <= 0 or height <= 0:
                return jsonify({'error': 'width and height must be positive integers'}), 400
        except (TypeError, ValueError):
            return jsonify({'error': 'width and height must be valid integers'}), 400
        
        logger.debug(f"Processing request with prompt: {prompt}, dimensions: {width}x{height}")
        
        # Load the Flux workflow template
        try:
            workflow = load_workflow('Flux API')
        except Exception as e:
            logger.error(f"Error loading workflow: {str(e)}")
            return jsonify({'error': 'Failed to load workflow template'}), 500
        
        # Update the workflow with the provided prompts and dimensions
        workflow['6']['inputs']['text'] = prompt
        workflow['33']['inputs']['text'] = negative_prompt
        
        # Update dimensions in the workflow
        # Note: You'll need to adjust these node IDs based on your actual workflow
        workflow['27']['inputs']['width'] = width
        workflow['27']['inputs']['height'] = height
        
        # Format the workflow for ComfyUI
        prompt_data = {
            "prompt": workflow,
            "client_id": "flux_api"
        }
        
        logger.debug(f"Sending workflow to ComfyUI: {json.dumps(prompt_data)}")
        
        # Send the workflow to ComfyUI with no-cache headers
        try:
            response = requests.post(
                f"{COMFYUI_URL}/prompt", 
                json=prompt_data,
                headers=NO_CACHE_HEADERS
            )
            response.raise_for_status()  # Raise exception for bad status codes
        except requests.RequestException as e:
            logger.error(f"Error sending workflow to ComfyUI: {str(e)}")
            if hasattr(e.response, 'text'):
                logger.error(f"ComfyUI response: {e.response.text}")
            return jsonify({'error': 'Failed to communicate with ComfyUI server'}), 500
            
        prompt_id = response.json().get('prompt_id')
        if not prompt_id:
            logger.error("No prompt_id in ComfyUI response")
            return jsonify({'error': 'Invalid response from ComfyUI server'}), 500
            
        logger.debug(f"Got prompt_id: {prompt_id}")
        
        return jsonify({
            'process_id': prompt_id,
            'status': 'queued'
        })
        
    except Exception as e:
        logger.error(f"Unexpected error in flux_text_to_image: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/flux-dev-text-to-image', methods=['POST'])
@api_key_required
def flux_dev_text_to_image():
    try:
        # Validate request data
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
            
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
            
        prompt = data.get('prompt')
        if not prompt:
            return jsonify({'error': 'prompt is required'}), 400
        
        # Get width and height with defaults from the workflow
        width = data.get('width', 1216)
        height = data.get('height', 832)
        
        # Validate width and height are positive integers
        try:
            width = int(width)
            height = int(height)
            if width <= 0 or height <= 0:
                return jsonify({'error': 'width and height must be positive integers'}), 400
        except (TypeError, ValueError):
            return jsonify({'error': 'width and height must be valid integers'}), 400
        
        logger.debug(f"Processing Flux Dev request with prompt: {prompt}, dimensions: {width}x{height}")
        
        # Load the Flux NSFW workflow template
        try:
            workflow = load_workflow('Flux NSFW')
        except Exception as e:
            logger.error(f"Error loading workflow: {str(e)}")
            return jsonify({'error': 'Failed to load workflow template'}), 500
        
        # Update the workflow with the provided prompt and dimensions
        workflow['6']['inputs']['text'] = prompt
        
        # Update dimensions in the workflow (both EmptySD3LatentImage and ModelSamplingFlux)
        workflow['27']['inputs']['width'] = width
        workflow['27']['inputs']['height'] = height
        workflow['30']['inputs']['width'] = width
        workflow['30']['inputs']['height'] = height
        
        # Ensure the diffusion model is set to flux1-dev.safetensors
        workflow['12']['inputs']['unet_name'] = "flux1-dev.safetensors"
        
        # Format the workflow for ComfyUI
        prompt_data = {
            "prompt": workflow,
            "client_id": "flux_dev_api"
        }
        
        logger.debug(f"Sending Flux Dev workflow to ComfyUI: {json.dumps(prompt_data)}")
        
        # Send the workflow to ComfyUI with no-cache headers
        try:
            response = requests.post(
                f"{COMFYUI_URL}/prompt", 
                json=prompt_data,
                headers=NO_CACHE_HEADERS
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error sending workflow to ComfyUI: {str(e)}")
            if hasattr(e.response, 'text'):
                logger.error(f"ComfyUI response: {e.response.text}")
            return jsonify({'error': 'Failed to communicate with ComfyUI server'}), 500
            
        prompt_id = response.json().get('prompt_id')
        if not prompt_id:
            logger.error("No prompt_id in ComfyUI response")
            return jsonify({'error': 'Invalid response from ComfyUI server'}), 500
            
        logger.debug(f"Got prompt_id: {prompt_id}")
        
        return jsonify({
            'process_id': prompt_id,
            'status': 'queued'
        })
        
    except Exception as e:
        logger.error(f"Unexpected error in flux_dev_text_to_image: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/flux-schnell-text-to-image', methods=['POST'])
@api_key_required
def flux_schnell_text_to_image():
    try:
        # Validate request data
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
            
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
            
        prompt = data.get('prompt')
        if not prompt:
            return jsonify({'error': 'prompt is required'}), 400
        
        # Get width and height with defaults from the workflow
        width = data.get('width', 1216)
        height = data.get('height', 832)
        
        # Validate width and height are positive integers
        try:
            width = int(width)
            height = int(height)
            if width <= 0 or height <= 0:
                return jsonify({'error': 'width and height must be positive integers'}), 400
        except (TypeError, ValueError):
            return jsonify({'error': 'width and height must be valid integers'}), 400
        
        logger.debug(f"Processing Flux Schnell request with prompt: {prompt}, dimensions: {width}x{height}")
        
        # Load the Flux NSFW workflow template
        try:
            workflow = load_workflow('Flux NSFW')
        except Exception as e:
            logger.error(f"Error loading workflow: {str(e)}")
            return jsonify({'error': 'Failed to load workflow template'}), 500
        
        # Update the workflow with the provided prompt and dimensions
        workflow['6']['inputs']['text'] = prompt
        
        # Update dimensions in the workflow (both EmptySD3LatentImage and ModelSamplingFlux)
        workflow['27']['inputs']['width'] = width
        workflow['27']['inputs']['height'] = height
        workflow['30']['inputs']['width'] = width
        workflow['30']['inputs']['height'] = height
        
        # Set the diffusion model to flux-schnell.safetensors
        workflow['12']['inputs']['unet_name'] = "flux-schnell.safetensors"
        
        # Format the workflow for ComfyUI
        prompt_data = {
            "prompt": workflow,
            "client_id": "flux_schnell_api"
        }
        
        logger.debug(f"Sending Flux Schnell workflow to ComfyUI: {json.dumps(prompt_data)}")
        
        # Send the workflow to ComfyUI with no-cache headers
        try:
            response = requests.post(
                f"{COMFYUI_URL}/prompt", 
                json=prompt_data,
                headers=NO_CACHE_HEADERS
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error sending workflow to ComfyUI: {str(e)}")
            if hasattr(e.response, 'text'):
                logger.error(f"ComfyUI response: {e.response.text}")
            return jsonify({'error': 'Failed to communicate with ComfyUI server'}), 500
            
        prompt_id = response.json().get('prompt_id')
        if not prompt_id:
            logger.error("No prompt_id in ComfyUI response")
            return jsonify({'error': 'Invalid response from ComfyUI server'}), 500
            
        logger.debug(f"Got prompt_id: {prompt_id}")
        
        return jsonify({
            'process_id': prompt_id,
            'status': 'queued'
        })
        
    except Exception as e:
        logger.error(f"Unexpected error in flux_schnell_text_to_image: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status/<process_id>', methods=['GET'])
@api_key_required
def check_status(process_id):
    try:
        result = requests.get(f"{COMFYUI_URL}/history/{process_id}", headers=NO_CACHE_HEADERS)
        if result.status_code == 200:
            history = result.json()
            try:
                if history[process_id]['status']['status_str'] == "success":
                    outputs = history[process_id]['outputs']
                    file_name = None
                    
                    # Process each node's output to get filename
                    for node_id, node_output in outputs.items():
                        if node_output.get('images'):
                            file_name = node_output['images'][0]['filename']
                            break
                        elif node_output.get('gifs'):
                            file_name = node_output['gifs'][0]['filename']
                            break
                    
                    return jsonify({
                        "process_id": process_id, 
                        "status": history[process_id]['status']['status_str'], 
                        "output": outputs,
                        "file_name": file_name
                    })
                else:
                    return jsonify({"process_id": process_id, "status": "queued"})
            except:
                return jsonify({"process_id": process_id, "status": "queued"})
        
    except Exception as e:
        logger.error(f"Unexpected error in check_status: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/wan-image-to-video', methods=['POST'])
@api_key_required
def wan_image_to_video():
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
            
        image_file = request.files['image']
        prompt = request.form.get('prompt', '')
        
        # Get optional parameters with defaults
        width = request.form.get('width', 512)
        height = request.form.get('height', 512)
        video_length = request.form.get('video_length', 4)  # Default 4 seconds
        
        # Validate numeric parameters
        try:
            width = int(width)
            height = int(height)
            video_length = int(video_length)
            if width <= 0 or height <= 0 or video_length <= 0:
                return jsonify({'error': 'width, height, and video_length must be positive integers'}), 400
        except (TypeError, ValueError):
            return jsonify({'error': 'width, height, and video_length must be valid integers'}), 400
        
        # Validate file type
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
        if '.' not in image_file.filename or \
           image_file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
            return jsonify({'error': 'Invalid file type. Allowed types: png, jpg, jpeg, gif'}), 400
        
        # Save the uploaded image to ComfyUI's input directory
        filename = secure_filename(image_file.filename)
        input_dir = '/workspace/ComfyUI/input'  # Use absolute path
        os.makedirs(input_dir, exist_ok=True)
        image_path = os.path.join(input_dir, filename)
        
        # Save the file
        image_file.save(image_path)
        
        # Verify the file was saved successfully
        if not os.path.exists(image_path):
            return jsonify({'error': 'Failed to save image file'}), 500
            
        logger.debug(f"Saved image to: {image_path}")
        logger.debug(f"File exists: {os.path.exists(image_path)}")
        logger.debug(f"File size: {os.path.getsize(image_path)} bytes")
        
        # Load the Wan workflow template
        try:
            workflow = load_workflow('Wan 2.1 API')
        except Exception as e:
            logger.error(f"Error loading workflow: {str(e)}")
            return jsonify({'error': 'Failed to load workflow template'}), 500
        
        # Update the workflow for image-to-video
        workflow['37']['inputs']['unet_name'] = "wan2.1_i2v_720p_14B_fp8_e4m3fn.safetensors"
        workflow['52']['inputs']['image'] = filename  # Use just the filename
        workflow['6']['inputs']['text'] = prompt
        workflow['50']['inputs']['width'] = width
        workflow['50']['inputs']['height'] = height
        workflow['50']['inputs']['length'] = video_length * 8  # Convert seconds to frames (8 fps)
        
        # Format the workflow for ComfyUI
        prompt_data = {
            "prompt": workflow,
            "client_id": "wan_i2v_api"
        }
        
        logger.debug(f"Sending workflow to ComfyUI: {json.dumps(prompt_data)}")
        
        # Send the workflow to ComfyUI with no-cache headers
        try:
            response = requests.post(
                f"{COMFYUI_URL}/prompt", 
                json=prompt_data,
                headers=NO_CACHE_HEADERS
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error sending workflow to ComfyUI: {str(e)}")
            if hasattr(e.response, 'text'):
                logger.error(f"ComfyUI response: {e.response.text}")
            return jsonify({'error': 'Failed to communicate with ComfyUI server'}), 500
            
        prompt_id = response.json().get('prompt_id')
        if not prompt_id:
            logger.error("No prompt_id in ComfyUI response")
            return jsonify({'error': 'Invalid response from ComfyUI server'}), 500
            
        logger.debug(f"Got prompt_id: {prompt_id}")
        
        return jsonify({
            'process_id': prompt_id,
            'status': 'queued'
        })
        
    except Exception as e:
        # Clean up temporary file in case of error
        if 'image_path' in locals() and os.path.exists(image_path):
            os.remove(image_path)
        logger.error(f"Unexpected error in wan_image_to_video: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/wan-text-to-video', methods=['POST'])
@api_key_required
def wan_text_to_video():
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
            
        prompt = data.get('prompt')
        if not prompt:
            return jsonify({'error': 'prompt is required'}), 400
            
        negative_prompt = ''
        
        # Get optional parameters with defaults
        width = data.get('width', 512)
        height = data.get('height', 512)
        video_length = data.get('video_length', 4)  # Default 4 seconds
        
        # Validate numeric parameters
        try:
            width = int(width)
            height = int(height)
            video_length = int(video_length)
            if width <= 0 or height <= 0 or video_length <= 0:
                return jsonify({'error': 'width, height, and video_length must be positive integers'}), 400
        except (TypeError, ValueError):
            return jsonify({'error': 'width, height, and video_length must be valid integers'}), 400
        
        logger.debug(f"Processing request with prompt: {prompt}")
        
        # Load the Wan workflow template
        try:
            workflow = load_workflow('Wan 2.1 API')
        except Exception as e:
            logger.error(f"Error loading workflow: {str(e)}")
            return jsonify({'error': 'Failed to load workflow template'}), 500
        
        # Update the workflow for text-to-video
        workflow['37']['inputs']['unet_name'] = "wan2.1_t2v_1.3B_fp16.safetensors"
        workflow['6']['inputs']['text'] = prompt
        workflow['7']['inputs']['text'] = negative_prompt
        workflow['50']['inputs']['width'] = width
        workflow['50']['inputs']['height'] = height
        workflow['50']['inputs']['length'] = video_length * 8  # Convert seconds to frames (8 fps)
        
        # Format the workflow for ComfyUI
        prompt_data = {
            "prompt": workflow,
            "client_id": "wan_t2v_api"
        }
        
        logger.debug(f"Sending workflow to ComfyUI: {json.dumps(prompt_data)}")
        
        # Send the workflow to ComfyUI with no-cache headers
        try:
            response = requests.post(
                f"{COMFYUI_URL}/prompt", 
                json=prompt_data,
                headers=NO_CACHE_HEADERS
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error sending workflow to ComfyUI: {str(e)}")
            if hasattr(e.response, 'text'):
                logger.error(f"ComfyUI response: {e.response.text}")
            return jsonify({'error': 'Failed to communicate with ComfyUI server'}), 500
            
        prompt_id = response.json().get('prompt_id')
        if not prompt_id:
            logger.error("No prompt_id in ComfyUI response")
            return jsonify({'error': 'Invalid response from ComfyUI server'}), 500
            
        logger.debug(f"Got prompt_id: {prompt_id}")
        
        return jsonify({
            'process_id': prompt_id,
            'status': 'queued'
        })
        
    except Exception as e:
        logger.error(f"Unexpected error in wan_text_to_video: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/framepack-image-to-video', methods=['POST'])
@api_key_required
def framepack_image_to_video():
    try:
        if 'start_image' not in request.files or 'end_image' not in request.files:
            return jsonify({'error': 'Both start_image and end_image files are required'}), 400
            
        start_image = request.files['start_image']
        end_image = request.files['end_image']
        prompt = request.form.get('prompt', '')
        
        # Validate file types
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif'}
        for image_file in [start_image, end_image]:
            if '.' not in image_file.filename or \
               image_file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
                return jsonify({'error': f'Invalid file type for {image_file.filename}. Allowed types: png, jpg, jpeg, gif'}), 400
        
        # Save the uploaded images to ComfyUI's input directory
        start_filename = secure_filename(start_image.filename)
        end_filename = secure_filename(end_image.filename)
        input_dir = '/workspace/ComfyUI/input'  # Use absolute path
        os.makedirs(input_dir, exist_ok=True)
        
        start_path = os.path.join(input_dir, start_filename)
        end_path = os.path.join(input_dir, end_filename)
        
        # Save the files
        start_image.save(start_path)
        end_image.save(end_path)
        
        # Verify the files were saved successfully
        if not os.path.exists(start_path) or not os.path.exists(end_path):
            return jsonify({'error': 'Failed to save image files'}), 500
            
        logger.debug(f"Saved start image to: {start_path}")
        logger.debug(f"Start image exists: {os.path.exists(start_path)}")
        logger.debug(f"Start image size: {os.path.getsize(start_path)} bytes")
        logger.debug(f"Saved end image to: {end_path}")
        logger.debug(f"End image exists: {os.path.exists(end_path)}")
        logger.debug(f"End image size: {os.path.getsize(end_path)} bytes")
        
        # Load the FramePack workflow template
        try:
            workflow = load_workflow('FramePack API')
        except Exception as e:
            logger.error(f"Error loading workflow: {str(e)}")
            return jsonify({'error': 'Failed to load workflow template'}), 500
        
        # Update the workflow with both images and prompt
        workflow['19']['inputs']['image'] = start_filename  # Start image
        workflow['58']['inputs']['image'] = end_filename    # End image
        workflow['47']['inputs']['text'] = prompt
        
        # Format the workflow for ComfyUI
        prompt_data = {
            "prompt": workflow,
            "client_id": "framepack_api"
        }
        
        logger.debug(f"Sending workflow to ComfyUI: {json.dumps(prompt_data)}")
        
        # Send the workflow to ComfyUI with no-cache headers
        try:
            response = requests.post(
                f"{COMFYUI_URL}/prompt", 
                json=prompt_data,
                headers=NO_CACHE_HEADERS
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error sending workflow to ComfyUI: {str(e)}")
            if hasattr(e.response, 'text'):
                logger.error(f"ComfyUI response: {e.response.text}")
            return jsonify({'error': 'Failed to communicate with ComfyUI server'}), 500
            
        prompt_id = response.json().get('prompt_id')
        if not prompt_id:
            logger.error("No prompt_id in ComfyUI response")
            return jsonify({'error': 'Invalid response from ComfyUI server'}), 500
            
        logger.debug(f"Got prompt_id: {prompt_id}")
        
        return jsonify({
            'process_id': prompt_id,
            'status': 'queued'
        })
        
    except Exception as e:
        # Clean up temporary files in case of error
        if 'start_path' in locals() and os.path.exists(start_path):
            os.remove(start_path)
        if 'end_path' in locals() and os.path.exists(end_path):
            os.remove(end_path)
        logger.error(f"Unexpected error in framepack_image_to_video: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/download/<filename>', methods=['GET'])
@api_key_required
def download_file(filename):
    try:
        # Check multiple possible locations for the file
        possible_paths = [
            f"/workspace/ComfyUI/output/{filename}",
            f"/ComfyUI/output/{filename}",
            f"/tmp/latentsync_b9e6a424/latentsync_1076d504/{filename}"
        ]
        
        file_path = None
        for path in possible_paths:
            if os.path.exists(path):
                file_path = path
                break
        
        if not file_path:
            return jsonify({'error': 'File not found in any of the expected locations'}), 404
            
        # Determine content type based on file extension
        content_type = 'application/octet-stream'
        if filename.endswith('.png'):
            content_type = 'image/png'
        elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
            content_type = 'image/jpeg'
        elif filename.endswith('.mp4'):
            content_type = 'video/mp4'
        elif filename.endswith('.gif'):
            content_type = 'image/gif'
        
        logger.debug(f"Serving file from: {file_path}")
        
        return send_file(
            file_path,
            mimetype=content_type,
            as_attachment=True,
            download_name=filename
        )
            
    except Exception as e:
        logger.error(f"Error downloading file {filename}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/text-to-video', methods=['POST'])
@api_key_required
def text_to_video():
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
            
        prompt = data.get('prompt')
        if not prompt:
            return jsonify({'error': 'prompt is required'}), 400
            
        # Get optional parameters with defaults
        width = data.get('width', 1920)  # Default from workflow
        height = data.get('height', 1088)  # Default from workflow
        video_length = data.get('video_length', 4)  # Default 4 seconds
        
        # Validate numeric parameters
        try:
            width = int(width)
            height = int(height)
            video_length = int(video_length)
            if width <= 0 or height <= 0 or video_length <= 0:
                return jsonify({'error': 'width, height, and video_length must be positive integers'}), 400
        except (TypeError, ValueError):
            return jsonify({'error': 'width, height, and video_length must be valid integers'}), 400
        
        logger.debug(f"Processing request with prompt: {prompt}")
        
        # Load the Wan workflow template
        try:
            workflow = load_workflow('text_to_video_wan')
        except Exception as e:
            logger.error(f"Error loading workflow: {str(e)}")
            return jsonify({'error': 'Failed to load workflow template'}), 500
        
        # Update the workflow with the provided parameters
        workflow['6']['inputs']['text'] = prompt  # Positive prompt
        workflow['40']['inputs']['width'] = width
        workflow['40']['inputs']['height'] = height
        workflow['40']['inputs']['length'] = video_length * 8  # Convert seconds to frames (8 fps)
        
        # Format the workflow for ComfyUI
        prompt_data = {
            "prompt": workflow,
            "client_id": "text_to_video_api"
        }
        
        logger.debug(f"Sending workflow to ComfyUI: {json.dumps(prompt_data)}")
        
        # Send the workflow to ComfyUI with no-cache headers
        try:
            response = requests.post(
                f"{COMFYUI_URL}/prompt", 
                json=prompt_data,
                headers=NO_CACHE_HEADERS
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error sending workflow to ComfyUI: {str(e)}")
            if hasattr(e.response, 'text'):
                logger.error(f"ComfyUI response: {e.response.text}")
            return jsonify({'error': 'Failed to communicate with ComfyUI server'}), 500
            
        prompt_id = response.json().get('prompt_id')
        if not prompt_id:
            logger.error("No prompt_id in ComfyUI response")
            return jsonify({'error': 'Invalid response from ComfyUI server'}), 500
            
        logger.debug(f"Got prompt_id: {prompt_id}")
        
        return jsonify({
            'process_id': prompt_id,
            'status': 'queued'
        })
        
    except Exception as e:
        logger.error(f"Unexpected error in text_to_video: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Add template filter for datetime formatting
@app.template_filter('datetime')
def format_datetime(timestamp):
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3002, debug=True)

