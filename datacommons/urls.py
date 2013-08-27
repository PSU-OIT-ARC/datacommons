from django.conf.urls import patterns, include, url
from .views import csv, doc, schemas, api, shapefile, accounts, querybuilder

# Uncomment the next two lines to enable the admin:
from django.contrib import admin
admin.autodiscover()

urlpatterns = patterns('',
    url(r'^$', accounts.login, name='home'),

    # csvs
    url(r'^csv/upload/?$', csv.upload, name='csv-upload'),
    url(r'^csv/preview/?$', csv.preview, name="csv-preview"),

    # shapefiles
    url(r'^shapefile/upload/?$', shapefile.upload, name='shapefile-upload'),
    url(r'^shapefile/preview/?$', shapefile.preview, name="shapefile-preview"),

    # documents
    url(r'^doc/upload/?$', doc.upload, name='doc-upload'),
    url(r'^doc/?$', doc.all, name='doc-all'),
    url(r'^doc/download/(\d+)?$', doc.download, name='doc-download'),

    # query builder
    url(r'^querybuilder/?$', querybuilder.build, name="querybuilder-build"),
    url(r'^querybuilder/join/?$', querybuilder.join_, name="querybuilder-join"),

    # schemas
    url(r'^schemas/?$', schemas.all, name="schemas-all"),
    url(r'^schemas/view/(.*)/(.*)/?$', schemas.view, name="schemas-view"),
    url(r'^schema/permissions/?$', schemas.permissions, name="schemas-permissions"),
    url(r'^schema/users/?$', schemas.users, name="schemas-users"),
    url(r'^schema/grant/?$', schemas.grant, name="schemas-grant"),
    url(r'^schema/permissions/(\d+)/?$', schemas.permissionsDetail, name="schemas-permissions-detail"),
    url(r'^schemas/create/?$', schemas.create, name="schemas-create"),
    url(r'^schemas/restore/(\d+)/?$', schemas.restore, name="schemas-restore"),

    # api
    url(r'^api/schemas/(.*)/tables/(.*)\.(.*)$', api.view, name="api-schemas-tables"),
    url(r'^api/query/?$', api.query, name="api-query"),


    # Uncomment the admin/doc line below to enable admin documentation:
    # url(r'^admin/doc/', include('django.contrib.admindocs.urls')),

    # Uncomment the next line to enable the admin:
    url(r'^admin/', include(admin.site.urls)),

    # registration
    url(r'^register/?$', accounts.register, name="register"),
    url(r'^accounts/login/?$', accounts.login, name="login"),
    url(r'^accounts/profile/?$', accounts.profile, name="profile"),
    url(r'^accounts/logout/?$', 'django.contrib.auth.views.logout', {"next_page": "/"}, name="logout"),
    url(r'^accounts/settings/?$', accounts.settings, name="settings"),
    url(r'^accounts/password/?$', accounts.password, name="password"),

    # reset password
    url(r'^accounts/reset/?$', 'django.contrib.auth.views.password_reset', {"from_email": "django@pdx.edu"}),
    url(r'^accounts/reset/done/?$', 'django.contrib.auth.views.password_reset_done'),
    url(r'^accounts/reset/confirm/(?P<uidb36>[0-9A-Za-z]+)-(?P<token>.+)', 'django.contrib.auth.views.password_reset_confirm'),
    url(r'^accounts/reset/complete/?$', 'django.contrib.auth.views.password_reset_complete'),
)
