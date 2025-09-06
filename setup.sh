#!/bin/bash

PROJECT_DIR="$HOME/projects/ianua"
VENV_DIR="$PROJECT_DIR/.venv"

echo "Setting up Android Device Fetcher..."

mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

echo "Installing requirements..."
pip install --upgrade pip
pip install -r requirements.txt

cat > "$PROJECT_DIR/db_setup.py" << 'EOF'
#!/usr/bin/env python3

import sys
from pathlib import Path
import psycopg2
from psycopg2 import sql
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import ProgrammingError, OperationalError

sys.path.append(str(Path.home() / "projects" / "ianua"))

from config import DB_CONFIG, Base, Device, DeviceStatus

def check_database_exists(db_config):
    try:
        conn = psycopg2.connect(
            host=db_config['host'],
            port=db_config['port'],
            user=db_config['user'],
            password=db_config['password'],
            database='postgres'
        )
        conn.autocommit = True
        cursor = conn.cursor()

        cursor.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (db_config['database'],)
        )
        exists = cursor.fetchone() is not None

        cursor.close()
        conn.close()
        return exists
    except Exception as e:
        print(f"Error checking database: {e}")
        return False

def create_database(db_config):
    try:
        conn = psycopg2.connect(
            host=db_config['host'],
            port=db_config['port'],
            user=db_config['user'],
            password=db_config['password'],
            database='postgres'
        )
        conn.autocommit = True
        cursor = conn.cursor()

        cursor.execute(
            sql.SQL("CREATE DATABASE {}").format(
                sql.Identifier(db_config['database'])
            )
        )
        print(f"Database '{db_config['database']}' created successfully")

        cursor.close()
        conn.close()
        return True
    except psycopg2.errors.DuplicateDatabase:
        print(f"Database '{db_config['database']}' already exists")
        return True
    except Exception as e:
        print(f"Error creating database: {e}")
        return False

def setup_database():
    if not check_database_exists(DB_CONFIG):
        print(f"Database '{DB_CONFIG['database']}' does not exist. Creating...")
        if not create_database(DB_CONFIG):
            print("Failed to create database")
            return False
    else:
        print(f"Database '{DB_CONFIG['database']}' already exists")

    database_url = (
        f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
        f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
    )

    try:
        engine = create_engine(database_url)

        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()

        tables_to_create = []
        for table in Base.metadata.tables.values():
            if table.name not in existing_tables:
                tables_to_create.append(table.name)

        if tables_to_create:
            print(f"Creating tables: {', '.join(tables_to_create)}")
            Base.metadata.create_all(engine, checkfirst=True)
            print("Tables created successfully")
        else:
            print("All tables already exist")

        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            test_query = session.query(Device).limit(1).all()
            print("Database connection test successful")
        except Exception as e:
            print(f"Database query test failed: {e}")
        finally:
            session.close()

        engine.dispose()
        return True

    except OperationalError as e:
        print(f"Database connection error: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False

if __name__ == "__main__":
    print("Starting database setup...")
    if setup_database():
        print("Database setup completed successfully")
        sys.exit(0)
    else:
        print("Database setup failed")
        sys.exit(1)
EOF

echo "Creating PostgreSQL user if not exists..."
sudo -u postgres psql -tc "SELECT 1 FROM pg_user WHERE usename = 'dbw'" | grep -q 1 || \
sudo -u postgres psql <<EOF
CREATE USER dbw WITH PASSWORD '123';
EOF

sudo -u postgres psql <<EOF
ALTER USER dbw CREATEDB;
EOF

echo "Setting up database..."
python "$PROJECT_DIR/db_setup.py"

if [ $? -ne 0 ]; then
    echo "Database setup failed. Exiting..."
    exit 1
fi

echo "Setting up ADB..."
if ! command -v adb &> /dev/null; then
    echo "Installing ADB..."
    sudo apt-get update
    sudo apt-get install -y android-tools-adb android-tools-fastboot
fi

echo "Setup complete!"
