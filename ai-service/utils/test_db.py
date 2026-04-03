from pymongo import MongoClient

uri = "mongodb+srv://jayasharmanaidu_db_user:jaya1204@homegrowcluster.ao3dmba.mongodb.net/?appName=HomeGrowCluster"

client = MongoClient(uri)
print(client.list_database_names())