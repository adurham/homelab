import psycopg2
import psycopg2.extras

def connect_to_db(dbname, user, host, port):
    conn = psycopg2.connect(dbname=dbname, user=user, host=host, port=port)
    return conn

def get_all_databases(conn):
    databases = []
    cur = conn.cursor()
    cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
    for db in cur.fetchall():
        databases.append(db[0])
    cur.close()
    return databases

def check_md5_indexes(conn):
    query = """
    SELECT 
        t.relname AS table_name,
        i.relname AS index_name,
        pg_get_indexdef(i.oid) AS index_definition
    FROM 
        pg_class t,
        pg_class i,
        pg_index ix
    WHERE 
        t.oid = ix.indrelid
        AND i.oid = ix.indexrelid
        AND pg_get_indexdef(i.oid) LIKE '%md5%';
    """
    cur = conn.cursor()
    cur.execute(query)
    indexes = cur.fetchall()
    cur.close()
    return indexes

def main():
    user = ''
    host = ''
    port = ''

    # Connect to the default database (usually postgres) to list all other databases
    conn = connect_to_db('postgres', user, host, port)
    databases = get_all_databases(conn)
    conn.close()

    for dbname in databases:
        try:
            conn = connect_to_db(dbname, user, host, port)
            print(f"Checking database: {dbname}")
            indexes = check_md5_indexes(conn)
            if indexes:
                for idx in indexes:
                    print(f"Database: {dbname}, Table: {idx[0]}, Index: {idx[1]}, Definition: {idx[2]}")
            else:
                print(f"No MD5 indexes found in {dbname}.")
            conn.close()
        except Exception as e:
            print(f"Could not check {dbname}: {str(e)}")

if __name__ == "__main__":
    main()
