# datacommons upload tool

## install

### python environment

    virtualenv-2.6 --no-site-packages .env
    source .env/bin/activate
    pip install -r requirements.txt

If you run into problems installing psycopg make sure you can execute the
`pg_config` command. If not, you need to add the directory containing pg_config
to your path. You can find the path with `locate pg_config`. On my machine, I
had to do:

    export PATH=/usr/pgsql-9.2/bin:$PATH


### dirs and files

    mkdir htdocs/media
    chown apache htdocs/media
    cp datacommons/demo_settings.py datacommons/local_settings.py

### Configure

Edit datacommons/local_settings.py and update the appropriate settings. Ask
someone on the project for the credentials to the dev DB, since mdj2 hasn't
figured out a way to deploy the DB locally.

### Run

Assuming you already sourced the environment (i.e. source .env/bin/activate),
use the following command to start the Django web server:

    ./bin/manage.py runserver 0.0.0.0:8000

### vhost

See vhost/prod.conf for example. Install it, reload apache

    touch datacommons/wsgi.py
