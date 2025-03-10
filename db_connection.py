from pymongo.mongo_client import MongoClient

def get_mongo_client():
    # Provide your MongoDB URI here
    uri = "mongodb+srv://moreyeahsaimldatascience:WMelEMakMwCiPygO@aimlmoreyeahs.8vjae.mongodb.net/?retryWrites=true&w=majority&appName=aimlmoreyeahs&ssl=True"

    client = MongoClient(uri)
    try:
        client.admin.command('ping')
        print("Pinged your deployment. You successfully connected to MongoDB!")
    except Exception as e:
        print(f"An error occurred while connecting to MongoDB: {e}")
        client = None
    return client
