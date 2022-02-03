from boto.s3.connection import S3Connection
from boto.s3.key import Key
import os
from time import strftime, gmtime

def init_s3():
    start = strftime("%Y-%m-%d-%H", gmtime())

    REGION_HOST = os.environ["AWS_REGION"]
    BUCKET_NAME = os.environ["BUCKET_NAME"]
    conn = S3Connection(os.environ['AWS_ID'], os.environ['AWS_SECRET'], host=REGION_HOST)
    mybucket = conn.get_bucket(BUCKET_NAME)
    for file in os.listdir("data/files/" + start):
            k = Key(mybucket)
            k.key = file
            k.set_contents_from_filename(os.path.join("data/files/" + start + "/", file))
