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

Configure datacommons/local_settings.py

### db
    cd bin && ./manage.py syncdb && cd ..

### vhost
See vhost/prod.conf for example. Install it, reload apache
    touch datacommons/wsgi.py
