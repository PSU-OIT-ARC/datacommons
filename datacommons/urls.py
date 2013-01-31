from django.conf.urls import patterns, include, url
from .views import home, csv, doc

# Uncomment the next two lines to enable the admin:
from django.contrib import admin
admin.autodiscover()

urlpatterns = patterns('',
    # Examples:
    url(r'^$', home.index, name='home'),
    url(r'^csv/upload/?$', csv.upload, name='csv-upload'),
    url(r'^csv/preview/?$', csv.preview, name="csv-preview"),
    url(r'^csv/?$', csv.all, name="csv-all"),
    url(r'^csv/view/(.*)/(.*)/?$', csv.view, name="csv-view"),
    # url(r'^datacommons/', include('datacommons.foo.urls')),
    url(r'^doc/upload/?$', doc.upload, name='doc-upload'),
    url(r'^doc/??$', doc.all, name='doc-all'),

    # Uncomment the admin/doc line below to enable admin documentation:
    # url(r'^admin/doc/', include('django.contrib.admindocs.urls')),

    # Uncomment the next line to enable the admin:
    url(r'^admin/', include(admin.site.urls)),


    # registration
    url(r'^register/?$', home.register),
    url(r'^accounts/login/?$', 'django.contrib.auth.views.login'),
    url(r'^accounts/profile/?$', home.profile, name="account-home"),
    url(r'^accounts/logout/?$', 'django.contrib.auth.views.logout', {"next_page": "/"}),

    # reset password
    url(r'^accounts/reset/?$', 'django.contrib.auth.views.password_reset', {"from_email": "django@pdx.edu"}),
    url(r'^accounts/reset/done/?$', 'django.contrib.auth.views.password_reset_done'),
    url(r'^accounts/reset/confirm/(?P<uidb36>[0-9A-Za-z]+)-(?P<token>.+)', 'django.contrib.auth.views.password_reset_confirm'),
    url(r'^accounts/reset/complete/?$', 'django.contrib.auth.views.password_reset_complete'),
)
