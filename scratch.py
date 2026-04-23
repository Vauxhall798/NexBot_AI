import pymssql
import pandas as pd

server = '103.235.104.222' 
database = 'TEST' 
username = 'R45TESTUSER' 
password = 'softadmin@123' 

try:
    conn = pymssql.connect(server=server, user=username, password=password, database=database)
    query = "SELECT * FROM TEST.R45TESTUSER.ItineraryMaster"
    df = pd.read_sql_query(query, conn)
    
    # Search for 'maldives' in any column
    mask = df.astype(str).apply(lambda x: x.str.contains('maldives', case=False, na=False))
    matches = df[mask.any(axis=1)]
    
    print(f"Found {len(matches)} matches in ItineraryMaster.")
    if len(matches) > 0:
        for col in df.columns:
            if mask[col].any():
                print(f"Match found in column: {col}")
                print(matches[col].tolist())
except Exception as e:
    print(f"Error: {e}")
