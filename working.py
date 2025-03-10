from flask import Flask, request, render_template, jsonify, redirect, url_for, flash, send_file
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
import os
import gridfs
import requests
from datetime import datetime, timedelta
import logging
from db_connection import get_mongo_client
from regenerate import MarketingContentGenerator

import threading
# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_signup'

# MongoDB connection
client = get_mongo_client()
db = client["Marketing_data"]
company_details = db["company_details"]
COMPANY_COLLECTION = "company_details"
users = db["users"]
fs = gridfs.GridFS(db)

# User model for Flask-Login
class User(UserMixin):
    def __init__(self, user_id, username, password_hash):
        self.id = user_id
        self.username = username
        self.password_hash = password_hash

    @classmethod
    def get_by_username(cls, username):
        user_data = users.find_one({"username": username})
        if user_data:
            return cls(str(user_data["_id"]), user_data["username"], user_data["password_hash"])
        return None

@login_manager.user_loader
def load_user(user_id):
    try:
        user_data = users.find_one({"_id": ObjectId(user_id)})
    except Exception as e:
        logger.error(f"Error loading user: {e}")
        return None
    
    if user_data:
        return User(str(user_data["_id"]), user_data["username"], user_data["password_hash"])
    return None

@app.route('/', methods=['GET', 'POST'])
def login_signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'login':
            username = request.form['username_login']
            password = request.form['password_login']
            user = User.get_by_username(username)

            if user and check_password_hash(user.password_hash, password):
                login_user(user)
                flash("Login successful!")
                return redirect(url_for('index'))
            else:
                flash("Invalid username or password.")
                return render_template('login_signup.html')

        elif action == 'signup':
            username = request.form['username_signup']
            password = request.form['password_signup']
            
            if len(password) < 6:
                flash("Password must be at least 6 characters long.")
                return render_template('login_signup.html')

            existing_user = users.find_one({"username": username})
            if existing_user:
                flash("Username already exists.")
                return render_template('login_signup.html')

            hashed_password = generate_password_hash(password)
            email = request.form['email_signup']

            existing_email = users.find_one({"email": email})
            if existing_email:
                flash("Email already exists.")
                return render_template('login_signup.html')

            users.insert_one({
                "username": username,
                "email": email,
                "password_hash": hashed_password,
                "created_at": datetime.utcnow()
            })
            flash("Signup successful! Please log in.")
            return redirect(url_for('login_signup'))

    return render_template('login_signup.html')

@app.route('/index')
@login_required
def index():
    return render_template('base.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("You have been logged out.")
    return redirect(url_for('login_signup'))

@app.route('/register')
@login_required
def register():
    # Check if user already has a registered company
    existing_company = company_details.find_one({"user_id": str(current_user.id)})
    if existing_company:
        flash("You already have a registered company. Please use the modify page to make changes.", "warning")
        return redirect(url_for('modify'))
    return render_template('register.html')

@app.route('/submit', methods=['POST'])
@login_required
def submit_data():
    try:
        # Check if the user has already registered a company
        existing_company = company_details.find_one({"user_id": str(current_user.id)})
        if existing_company:
            flash("You have already registered a company. Please use the modify page to make changes.", "warning")
            return redirect(url_for('modify'))

        # Collect form data
        company_data = {
            'user_id': str(current_user.id),
            'company_name': request.form.get('company_name'),
            'business_domain': request.form.get('business_domain'),
            'specific_focus': request.form.get('specific_focus'),
            'target_audience': request.form.get('target_audience'),
            'key_features': request.form.get('key_features'),
            'unique_selling_points': request.form.get('unique_selling_points'),
            'pricing_packages': request.form.get('pricing_packages'),
            'days': int(request.form.get('days')),
            'target_platform': request.form.getlist('target_platform'),
            'products_or_services': request.form.get('products_or_services'),
            'created_at': datetime.utcnow()
        }

        # Handle posting schedule
        posting_schedule_type = request.form.get('posting_schedule_type')
        if posting_schedule_type == "daily":
            company_data['posting_schedule'] = {"type": "daily"}
        else:
            specific_days = request.form.getlist('specific_days')
            company_data['posting_schedule'] = {"type": "specific_days", "days": specific_days}

        # Handle logo upload
        if 'logo' in request.files:
            logo = request.files['logo']
            if logo and logo.filename:
                filename = secure_filename(logo.filename)
                logo_id = fs.put(logo, filename=filename)
                company_data['logo_id'] = logo_id

        # Insert into MongoDB
        result = company_details.insert_one(company_data)
        
        if result.inserted_id:
            flash("Company registered successfully!", "success")
            return redirect(url_for('index'))
        else:
            flash("Error registering company.", "danger")
            return redirect(url_for('register'))

    except Exception as e:
        logger.error(f"Error submitting company data: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/modify', methods=['GET', 'POST'])
@login_required
def modify():
    if request.method == 'POST':
        action = request.form.get('action')
        company_name = request.form.get('company_name')

        if not company_name:
            flash('Company name is required.', 'danger')
            return redirect(url_for('modify'))

        if action == 'update':
            update_data = {}
            fields = [
                'updated_company_name', 'business_domain', 'specific_focus',
                'target_audience', 'key_features', 'unique_selling_points',
                'pricing_packages', 'days', 'target_platform'
            ]

            for field in fields:
                value = request.form.get(field)
                if value:
                    key = "company_name" if field == "updated_company_name" else field
                    update_data[key] = value

            # Handle posting schedule
            posting_schedule_type = request.form.get('posting_schedule_type')
            if posting_schedule_type:
                if posting_schedule_type == "daily":
                    update_data['posting_schedule'] = {"type": "daily"}
                else:
                    specific_days = request.form.getlist('specific_days')
                    update_data['posting_schedule'] = {"type": "specific_days", "days": specific_days}

            # Handle logo update if provided
            if 'logo' in request.files:
                logo = request.files['logo']
                if logo and logo.filename:
                    filename = secure_filename(logo.filename)
                    logo_id = fs.put(logo, filename=filename)
                    update_data['logo_id'] = logo_id

            if update_data:
                result = company_details.update_one(
                    {
                        "company_name": company_name,
                        "user_id": str(current_user.id)
                    },
                    {"$set": update_data}
                )

                if result.modified_count > 0:
                    flash(f'Company "{company_name}" updated successfully!', 'success')
                else:
                    flash(f'No changes were made to "{company_name}".', 'warning')

        elif action == 'delete':
            result = company_details.delete_one({
                "company_name": company_name,
                "user_id": str(current_user.id)
            })

            if result.deleted_count > 0:
                flash(f'Company "{company_name}" deleted successfully.', 'success')
            else:
                flash(f'Company "{company_name}" not found.', 'warning')

        return redirect(url_for('modify'))

    # GET request - fetch user's companies
    user_companies = list(company_details.find({"user_id": str(current_user.id)}))
    return render_template('modify.html', companies=user_companies)

@app.route('/image/<image_id>')
def serve_image(image_id):
    try:
        image_data = fs.get(ObjectId(image_id))
        return send_file(
            image_data,
            mimetype='image/jpeg'
        )
    except Exception as e:
        logger.error(f"Error serving image {image_id}: {e}")
        return "Image not found", 404

@app.route('/regenerate_content')
@login_required
def regenerate_content():
    try:
        user_id = str(current_user.id)

        def generate_content_background(user_id):
            generator = MarketingContentGenerator()
            try:
                generator.run_marketing_content_pipeline(user_id)
            finally:
                generator.close_connection()

        thread = threading.Thread(target=generate_content_background, args=(user_id,))
        thread.start()
        
        flash("Content regeneration started. Please refresh the page in a few moments.", "info")
        return redirect(url_for('view_content'))
    except Exception as e:
        logger.error(f"Error starting content regeneration: {e}")
        flash("Error starting content regeneration.", "error")
        return redirect(url_for('view_content'))

@app.route('/view_content')
@login_required
def view_content():
    try:
        user_companies = list(company_details.find({"user_id": str(current_user.id)}))
        
        all_content = []
        for company in user_companies:
            company_name = company['company_name']
            collection_name = f"marketing_content_{company_name.lower().replace(' ', '_')}"
            
            content_collection = db[collection_name]
            company_content = list(content_collection.find())
            
            for content in company_content:
                content['company_name'] = company_name
                content['_id'] = str(content['_id'])
                
                if 'image_id' in content and content['image_id'] is not None:
                    if isinstance(content['image_id'], dict) and '$oid' in content['image_id']:
                        content['image_id'] = content['image_id']['$oid']
                    else:
                        content['image_id'] = str(content['image_id'])
                
                if 'content_date' in content:
                    content['content_date'] = content['content_date'].strftime('%Y-%m-%d')
                if 'generated_at' in content:
                    content['generated_at'] = content['generated_at'].strftime('%Y-%m-%d %H:%M:%S')
                    
                all_content.append(content)
        
        return render_template('view_content.html', content=all_content)
        
    except Exception as e:
        logger.error(f"Error fetching content: {e}")
        flash("Error fetching content.", "error")
        return redirect(url_for('index'))


@app.route('/check_generation_status/<content_id>')
@login_required
def check_generation_status(content_id):
    try:
        # Get status from generation_status dictionary
        status = generation_status.get(content_id, {"status": "not_found"})
        
        if status["status"] == "completed":
            # Clear the status after sending it
            result = status.copy()
            del generation_status[content_id]
            
            # Structure the response data
            response_data = {
                "success": True,
                "status": "completed",
                "data": {
                    "content": result.get("content", {}),
                    "image_id": str(result.get("image_id")),
                    "generated_at": result.get("generated_at"),
                    "day": result.get("day"),
                    "day_of_week": result.get("day_of_week"),
                    "content_date": result.get("content_date")
                }
            }
            return jsonify(response_data)
            
        elif status["status"] == "error":
            # Clear the error status after sending it
            result = status.copy()
            del generation_status[content_id]
            return jsonify({
                "success": False,
                "status": "error",
                "message": result.get("message", "Unknown error occurred")
            })
            
        else:
            return jsonify({
                "success": True,
                "status": "processing"
            })
            
    except Exception as e:
        logger.error(f"Error in check_generation_status: {e}")
        return jsonify({
            "success": False,
            "status": "error",
            "message": str(e)
        }), 500
    
generation_status = {}

@app.route('/regenerate_single_content/<content_id>')
@login_required
def regenerate_single_content(content_id):
    try:
        user_id = str(current_user.id)
        
        def generate_single_content_background(user_id, content_id):
            generator = MarketingContentGenerator()
            try:
                generation_status[content_id] = {"status": "processing"}
                
                # Fetch the content details
                content_data = None
                collection_name = None
                
                for company in generator.db[COMPANY_COLLECTION].find({"user_id": user_id}):
                    collection_name = f"marketing_content_{company['company_name'].lower().replace(' ', '_')}"
                    content = generator.db[collection_name].find_one({"_id": ObjectId(content_id)})
                    
                    if content:
                        # Regenerate just this specific content
                        new_content = generator.generate_marketing_content(company, content['product'])
                        if new_content:
                            image_result = generator.generate_image(new_content, company.get('logo_id'))
                            if image_result:
                                # Update the existing content
                                update_data = {
                                    "content": new_content,
                                    "image_path": image_result['image_path'],
                                    "image_id": image_result['image_id'],
                                    "generated_at": datetime.now()
                                }
                                
                                generator.db[collection_name].update_one(
                                    {"_id": ObjectId(content_id)},
                                    {"$set": update_data}
                                )
                                
                                # Store the updated content for status checking
                                generation_status[content_id] = {
                                    "status": "completed",
                                    "content": new_content,
                                    "image_id": image_result['image_id'],
                                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "day": content.get('day'),
                                    "day_of_week": content.get('day_of_week'),
                                    "content_date": content.get('content_date')
                                }
                                break
            except Exception as e:
                generation_status[content_id] = {
                    "status": "error",
                    "message": str(e)
                }
                logger.error(f"Error in background generation for content {content_id}: {e}")
            finally:
                generator.close_connection()

        # Start the generation in a background thread
        thread = threading.Thread(
            target=generate_single_content_background,
            args=(user_id, content_id)
        )
        thread.start()
        
        return jsonify({
            "success": True, 
            "message": "Content regeneration started",
            "content_id": content_id
        })
        
    except Exception as e:
        logger.error(f"Error regenerating content {content_id}: {e}")
        return jsonify({"success": False, "message": str(e)})


@app.route('/get_company_details/<company_name>')
@login_required
def get_company_details(company_name):
    company = company_details.find_one({
        'company_name': company_name,
        'user_id': str(current_user.id)
    })
    
    if company:
        company['_id'] = str(company['_id'])
        return jsonify(company)
    else:
        return jsonify({"error": "Company not found"}), 404


@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

@app.route('/manage_company', methods=['GET'])
@login_required
def manage_company():
    # Fetch the user's company
    company = company_details.find_one({"user_id": str(current_user.id)})
    return render_template('manage_company.html', company=company)

@app.route('/check_company_status')
@login_required
def check_company_status():
    # Check if user has a registered company
    company = company_details.find_one({"user_id": str(current_user.id)})
    return jsonify({
        "has_company": company is not None,
        "company_name": company["company_name"] if company else None
    })

@app.route('/update_company_details', methods=['POST'])
@login_required
def update_company_details():
    try:
        company = company_details.find_one({"user_id": str(current_user.id)})
        if not company:
            return jsonify({"error": "No company found"}), 404

        update_data = {}
        # Get all form fields
        for field in request.form:
            if request.form[field]:  # Only update if value is not empty
                update_data[field] = request.form[field]

        # Handle file upload if present
        if 'logo' in request.files:
            logo = request.files['logo']
            if logo and logo.filename:
                filename = secure_filename(logo.filename)
                logo_id = fs.put(logo, filename=filename)
                update_data['logo_id'] = logo_id

        # Update the company details
        result = company_details.update_one(
            {"user_id": str(current_user.id)},
            {"$set": update_data}
        )

        if result.modified_count > 0:
            return jsonify({"success": "Company details updated successfully"})
        else:
            return jsonify({"message": "No changes made"})

    except Exception as e:
        logger.error(f"Error updating company details: {e}")
        return jsonify({"error": str(e)}), 500

def init_app():
    """Initialize the Flask application with all configurations"""
    try:
        # Ensure all required collections exist
        required_collections = ['users', 'company_details']
        existing_collections = db.list_collection_names()
        
        for collection in required_collections:
            if collection not in existing_collections:
                db.create_collection(collection)
        
        # Create indexes for users collection
        users.create_index("username", unique=True)
        users.create_index("email", unique=True)
        
        # Clean up any documents with null user_id before creating the unique index
        cleanup_result = company_details.delete_many({"user_id": None})
        if cleanup_result.deleted_count > 0:
            logger.info(f"Cleaned up {cleanup_result.deleted_count} documents with null user_id")
        
        # Check for any duplicate company names for the same user
        pipeline = [
            {"$group": {
                "_id": {"user_id": "$user_id", "company_name": "$company_name"},
                "count": {"$sum": 1},
                "docs": {"$push": "$_id"}
            }},
            {"$match": {
                "count": {"$gt": 1}
            }}
        ]
        
        duplicates = list(company_details.aggregate(pipeline))
        for duplicate in duplicates:
            # Keep the most recent document and delete others
            docs_to_delete = duplicate['docs'][1:]  # Keep first document
            company_details.delete_many({"_id": {"$in": docs_to_delete}})
        
        # Now create the compound index
        try:
            company_details.create_index(
                [("user_id", 1), ("company_name", 1)], 
                unique=True,
                background=True  # Create index in background
            )
        except Exception as e:
            logger.error(f"Error creating index: {e}")
            # If index creation fails, create non-unique index
            company_details.create_index(
                [("user_id", 1), ("company_name", 1)],
                unique=False,
                background=True
            )
    
    except Exception as e:
        logger.error(f"Error during app initialization: {e}")
        # Continue with application startup even if index creation fails
    
    return app

if __name__ == '__main__':
    app = init_app()
    app.run(host='0.0.0.0', port=8000, debug=True)