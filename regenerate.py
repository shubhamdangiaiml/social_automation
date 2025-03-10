import os
import json
import logging
from datetime import datetime, timedelta
import requests
import pymongo
import google.generativeai as genai
from PIL import Image
import io
from gridfs import GridFS
import random

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MONGO_URI = "mongodb+srv://moreyeahsaimldatascience:WMelEMakMwCiPygO@aimlmoreyeahs.8vjae.mongodb.net/?retryWrites=true&w=majority&appName=aimlmoreyeahs"
DB_NAME = "Marketing_data"
COMPANY_COLLECTION = "company_details"

HF_API_URL_FLUX = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-dev"
HF_API_URL_MIDJOURNEY = "https://api-inference.huggingface.co/models/Jovie/Midjourney"
HF_HEADERS = {"Authorization": "Bearer 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"}

GEMINI_API_KEY = 'AIzaSyB9YriqATKbxNWoeeRh8EGmiMztrAIGtJ4'

class MarketingContentGenerator:
    def __init__(self):
        self.client = pymongo.MongoClient(MONGO_URI)
        self.db = self.client[DB_NAME]
        genai.configure(api_key=GEMINI_API_KEY)
        self.images_dir = os.path.join(os.getcwd(), 'images')
        os.makedirs(self.images_dir, exist_ok=True)

    def query_huggingface(self, payload, api_url):
        try:
            response = requests.post(api_url, headers=HF_HEADERS, json=payload)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"API call failed: {str(e)}")
            return None

    def generate_marketing_content(self, company_data, product):
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            input_prompt = f"""
            Generate unique marketing content for:
            - Company Name: {company_data.get('company_name', 'Unknown Company')}
            - Business Domain: {company_data.get('business_domain', 'Not Specified')}
            - Specific Focus: {company_data.get('specific_focus', 'General')}
            - Target Audience: {company_data.get('target_audience', 'All')}
            - Key Features: {company_data.get('key_features', 'Not Defined')}
            - Unique Selling Points: {company_data.get('unique_selling_points', 'Unique Value')}
            - Pricing & Packages: {company_data.get('pricing_packages', 'Competitive')}
            - Target Platform: {company_data.get('target_platform', 'Multi-platform')}
            - Product/Service: {product}

            Provide a JSON response with:
            - Title: Marketing title
            - Punchline: Catchy phrase
            - Content: 125-word description
            - Hashtags: 5 relevant hashtags
            - Keywords: 5 key descriptors

            Important: Avoid using any special characters like *, _, or other markdown symbols. Provide plain text only
            Important-Generate content according this-
            "Twitter": "Ensure the full content is below 250 characters.",
            "LinkedIn": "Content should be professional and detailed (up to 125 words).",
            "Instagram": "Make the content engaging.",
            "Facebook": "Create balanced content suitable for a broad audience.",
            """
            completion = model.generate_content([input_prompt])
            response_text = completion.text.strip()
            
            if response_text.startswith('```json'):
                response_text = response_text.replace('```json', '').strip()
            if response_text.endswith('```'):
                response_text = response_text[:-3].strip()
            content = json.loads(response_text)
            logger.info(f"Successfully generated content for {product}")
            return content
        except Exception as e:
            logger.error(f"Content generation error for {product}: {e}")
            return None

    def generate_image(self, content, logo_id):
        try:
            # model = genai.GenerativeModel('gemini-1.5-flash')
            # refinement_prompt = f"""
            # Create a detailed image prompt for marketing:
            # Punchline: {content.get('Punchline', 'Marketing Image')}
            # Ensure a professional, visually appealing marketing image.
            # """
            
            # refined_completion = model.generate_content([refinement_prompt])
            # refined_prompt = refined_completion.text.strip()
            model = genai.GenerativeModel('gemini-1.5-flash')
            punchline={content.get('Punchline', '')}
            print(punchline)
            refinement_prompt = f"""
            Create only one detailed and creative prompt for generating a marketing image using the following details:
            
            
        
            Please treat the {content.get('Punchline', '')} text as a final, impactful reveal on the image
            The image should be visually appealing, human-centric or Futuristic and Technological Themes and suitable for social media marketing.
            """
            
            note_in_prompt = """***Please treat the punchline text as the 'money shot' of the image. 
            Avoid unnecessary text, and ensure all text is grammatically correct and free of spelling errors for a professional and polished look.***"""
            
            refined_completion = model.generate_content([refinement_prompt])
            refined_prompt = refined_completion.text.strip()
            refined_prompt = note_in_prompt + refined_prompt
            response = self.query_huggingface({"inputs": refined_prompt}, HF_API_URL_FLUX)
            
            if response is None:
                response = self.query_huggingface({"inputs": refined_prompt}, HF_API_URL_MIDJOURNEY)

            if response is not None:
                image = Image.open(io.BytesIO(response.content))

                if logo_id:
                    try:
                        fs = GridFS(self.db)
                        logo_file = fs.get(logo_id)
                        logo = Image.open(io.BytesIO(logo_file.read())).convert("RGBA")
                        logo_size = (200, 100)
                        logo = logo.resize(logo_size)
                        image_width, image_height = image.size
                        logo_position = (image_width - logo_size[0] - 10, 10)
                        image_with_alpha = image.convert("RGBA")
                        image_with_alpha.paste(logo, logo_position, logo)
                        final_image = image_with_alpha.convert("RGB")
                    except Exception as logo_err:
                        logger.warning(f"Error retrieving or processing logo: {logo_err}")
                        final_image = image
                else:
                    final_image = image

                img_byte_arr = io.BytesIO()
                final_image.save(img_byte_arr, format='JPEG', quality=90)
                img_byte_arr.seek(0)

                fs = GridFS(self.db)
                image_id = fs.put(
                    img_byte_arr.getvalue(),
                    filename=f"{content.get('company_name', 'platform')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg",
                    content_type='image/jpeg'
                )

                company_name = str(content.get('company_name', 'default_company')).lower().replace(' ', '_')
                company_dir = os.path.join(self.images_dir, company_name)
                os.makedirs(company_dir, exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                image_filename = f"{content.get('company_name', 'platform')}_{timestamp}.jpg"
                image_path = os.path.join(company_dir, image_filename)
                final_image.save(image_path, quality=90)

                logger.info(f"Image saved for {company_name}: {image_path} with GridFS ID: {image_id}")
                return {'image_path': image_path, 'image_id': image_id}
                
            else:
                logger.error(f"Failed to generate image for {content}")
                return None
            
        except Exception as e:
            logger.error(f"Image generation error for {content}: {e}")
            return None

    def run_marketing_content_pipeline(self, company_id):
        # Fetch the specific company by ID from the database
        companies = list(self.db[COMPANY_COLLECTION].find({"user_id": str(company_id)}))
        
        if not companies:
            logger.warning(f"No companies found for user ID: {company_id}")
            return

        for company in companies:
            try:
                company_name = company.get('company_name', 'Unknown Company')
                products = company.get('products_or_services', [company_name])
                
                if isinstance(products, str):
                    products = [p.strip() for p in products.split(",") if p.strip()]
                    
                if not products:
                    logger.warning(f"No products or services found for {company_name}")
                    continue

                platforms = company.get("target_platform", ["General"])
                
                if isinstance(platforms, str):
                    platforms = [p.strip() for p in platforms.split(",") if p.strip()]
                    
                if not platforms:
                    logger.warning(f"No target platforms found for {company_name}, skipping.")
                    continue

                total_days = 1
                logo_id = company.get('logo_id', '')
                current_date = datetime.now()

                for platform in platforms:
                    for day in range(1, total_days + 1):
                        try:
                            content_date = current_date

                            if day <= len(products):
                                product = products[day - 1]
                            else:
                                product = random.choice(products)

                            content = self.generate_marketing_content(company, product)
                            if not content:
                                logger.error(f"Failed to generate content for {company_name} - {product} on {platform}")
                                continue

                            image_result = self.generate_image(content, logo_id)
                            if not image_result:
                                logger.error(f"Failed to generate image for {company_name} - {product}")
                                continue

                            marketing_content = {
                                'company': company_name,
                                'product': product,
                                'content': content,
                                'platform': platform,
                                'image_path': image_result['image_path'],
                                'image_id': image_result['image_id'],
                                'day': day,
                                'content_date': content_date,
                                'generated_at': datetime.now()
                            }
                            print(marketing_content)

                        except Exception as product_err:
                            logger.error(f"Error generating content for {company_name} - {product} on platform {platform}: {product_err}")

            except Exception as e:
                logger.error(f"Error processing company {company_name}: {e}")

    def close_connection(self):
        self.client.close()

def main():
    current_user_id = input("Enter your user ID: ")
    generator = MarketingContentGenerator()
    
    try:
        generator.run_marketing_content_pipeline(current_user_id)
    except Exception as e:
        logger.error(f"Pipeline execution error: {e}")
    finally:
        generator.close_connection()

if __name__ == '__main__':
    main()