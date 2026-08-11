# MongoDB data directory

This directory is an optional local `mongod --dbpath`. Runtime database files
are ignored by Git. Set `MONGODB_DATA_DIR` to use another location; the Django
application never starts `mongod` or creates database files here.
