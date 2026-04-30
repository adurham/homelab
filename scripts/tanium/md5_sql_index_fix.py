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

def drop_and_recreate_index(conn, table_name, index_name, index_definition):
    with conn.cursor() as cur:
        # Extract column names from the index definition
        columns = index_definition.split('(')[-1].split(')')[0]

        # Drop the old MD5 index
        drop_query = f"DROP INDEX {index_name};"
        cur.execute(drop_query)

        # Create the new SHA-256 index
        new_index_name = index_name.replace("md5", "sha256")  # Rename the index
        create_query = f"""
            CREATE INDEX {new_index_name} ON {table_name}
            USING hash ({columns} hashtext_ops);  -- Use hashtext_ops for SHA-256
        """
        cur.execute(create_query)

def check_md5_indexes_and_replace(conn):
    indexes = check_md5_indexes(conn)
    if indexes:
        for idx in indexes:
            dbname = conn.info.dbname  # Get current database name
            print(f"Database: {dbname}, Table: {idx['table_name']}, Index: {idx['index_name']}")
            drop_and_recreate_index(conn, idx['table_name'], idx['index_name'], idx['index_definition'])
            print(f"Dropped MD5 index '{idx['index_name']}' and recreated as SHA-256 index '{idx['index_name'].replace('md5', 'sha256')}'")
    else:
        print(f"No MD5 indexes found in {conn.info.dbname}.")

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
            check_md5_indexes_and_replace(conn)
            conn.close()
        except Exception as e:
            print(f"Could not check {dbname}: {str(e)}")

if __name__ == "__main__":
    main()
