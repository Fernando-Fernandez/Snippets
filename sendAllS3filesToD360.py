import boto3
import json
import time
import uuid

BUCKET = "ugep-ccaas-tmna-genai-datacloud"
LAMBDA_NAME = "ugep-ccaas-tmna-genai-datacloud-lambda-function"
PREFIX = "Files/"
REGION = "us-west-2"
DELAY = 0.5

print("🔌 Connecting to AWS...")
s3 = boto3.client("s3", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)

print(f"📂 Listing objects in s3://{BUCKET}/{PREFIX} ...")
paginator = s3.get_paginator("list_objects_v2")
objects = []
for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
  batch = page.get("Contents", [])
  objects.extend(batch)
  print(f" ...fetched {len(objects)} objects so far")

print(f"\n✅ Found {len(objects)} files total\n")

for i, obj in enumerate(objects, 1):
  key = obj["Key"]
  
  # Skip "folder" markers
  if key.endswith("/"):
    print(f"[{i}/{len(objects)}] ⏭️ Skipping folder marker: {key}")
    continue
  
  print(f"[{i}/{len(objects)}] 📤 Invoking Lambda for: {key} ...", end=" ", flush=True)
  
  event = {
        "Records": [
                      {
                        "eventVersion": "2.1",
                        "eventSource": "aws:s3",
                        "awsRegion": REGION,
                        "eventTime": obj["LastModified"].isoformat(),
                        "eventName": "ObjectCreated:Put",
                        "userIdentity": {"principalId": "MANUAL_TRIGGER"},
                        "requestParameters": {"sourceIPAddress": "127.0.0.1"},
                        "responseElements": {
                          "x-amz-request-id": str(uuid.uuid4()),
                          "x-amz-id-2": str(uuid.uuid4())
                        },
                        "s3": {
                          "s3SchemaVersion": "1.0",
                          "configurationId": "manualTrigger",
                          "bucket": {
                            "name": BUCKET,
                            "arn": f"arn:aws:s3:::{BUCKET}"
                          },
                          "object": {
                            "key": key,
                            "size": obj["Size"],
                            "eTag": obj["ETag"].strip('"'),
                            "sequencer": uuid.uuid4().hex[:18].upper()
                          }
                        }
                      }
                  ]
  }
  
  response = lam.invoke(
    FunctionName=LAMBDA_NAME,
    InvocationType="RequestResponse",
    Payload=json.dumps(event)
  )
  
  result = json.loads(response["Payload"].read())
  status = response["StatusCode"]
  print(f"→ HTTP {status}")

  if status != 200 or "errorMessage" in str(result):
    print(f" ⚠️ Error: {result}")

  time.sleep(DELAY)

print("\n🏁 Done!")
