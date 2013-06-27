# datacommons upload tool

## install

### python environment

    virtualenv-2.6 --no-site-packages .env
    source .env/bin/activate
    pip install -r requirements.txt

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
