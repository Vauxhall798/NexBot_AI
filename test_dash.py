import requests
import json
import time
import os

BASE_URL = "http://localhost:5000/api/v1"

# 1. Create a dummy CSV file
csv_content = """Date,Region,Sales,Profit,Category
2023-01-01,North,150,50,Electronics
2023-01-02,South,200,80,Furniture
2023-01-03,East,120,30,Electronics
2023-01-04,West,300,150,Clothing
2023-01-05,North,180,60,Clothing
"""
with open("test_data.csv", "w") as f:
    f.write(csv_content)

# 2. Upload the file
print("Uploading file...")
with open("test_data.csv", "rb") as f:
    resp = requests.post(f"{BASE_URL}/data/upload-file", files={"file": f}, headers={"Authorization": "Bearer test_key_123"})

print(resp.json())
source_id = resp.json().get("source_id")

# 3. Request a dashboard
print("\nRequesting dashboard...")
payload = {
    "message": "Create a dashboard showing sales and profit by region and category",
    "data_source_id": source_id,
    "type": "download"
}
resp2 = requests.post(f"{BASE_URL}/dashboard/generate", json=payload, headers={"Authorization": "Bearer test_key_123"})
print(resp2.status_code)
res = resp2.json()
print(res)

if res.get("success"):
    fname = res.get("filename")
    print(f"\nChecking downloaded file: {fname}")
    fpath = os.path.join("downloads", fname)
    with open(fpath, "r") as f:
        html = f.read()
    print("\n--- HTML PREVIEW ---")
    print(html[:1000])
    print("...")
    print(html[-1000:])
    
    # Check for dashboardData
    if "window.dashboardData =" in html:
        print("\n✅ Found window.dashboardData injection!")
    else:
        print("\n❌ Missing window.dashboardData!")
