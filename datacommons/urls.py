from django.conf.urls import patterns, include, url
from .views import home, csv, doc, schemas

# Uncomment the next two lines to enable the admin:
from django.contrib import admin
admin.autodiscover()

urlpatterns = patterns('',
    # Examples:
    url(r'^$', home.index, name='home'),
    url(r'^csv/upload/?$', csv.upload, name='csv-upload'),
    url(r'^csv/preview/?$', csv.preview, name="csv-preview"),

    url(r'^doc/upload/?$', doc.upload, name='doc-upload'),
    url(r'^doc/?$', doc.all, name='doc-all'),
    url(r'^doc/download/(\d+)?$', doc.download, name='doc-download'),

    # schemas
    url(r'^schemas/?$', schemas.all, name="schemas-all"),
    url(r'^schemas/view/(.*)/(.*)/?$', schemas.view, name="schemas-view"),
    url(r'^schema/permissions/?$', schemas.permissions, name="schemas-permissions"),
    url(r'^schema/users/?$', schemas.users, name="schemas-users"),
    url(r'^schema/grant/?$', schemas.grant, name="schemas-grant"),
    url(r'^schema/permissions/(\d+)/?$', schemas.permissionsDetail, name="schemas-permissions-detail"),


    # Uncomment the admin/doc line below to enable admin documentation:
    # url(r'^admin/doc/', include('django.contrib.admindocs.urls')),

    # Uncomment the next line to enable the admin:
    url(r'^admin/', include(admin.site.urls)),


    # registration
    url(r'^register/?$', home.register, name="register"),
    url(r'^accounts/login/?$', 'django.contrib.auth.views.login', name="login"),
    url(r'^accounts/profile/?$', home.profile, name="profile"),
    url(r'^accounts/logout/?$', 'django.contrib.auth.views.logout', {"next_page": "/"}, name="logout"),

    # reset password
    url(r'^accounts/reset/?$', 'django.contrib.auth.views.password_reset', {"from_email": "django@pdx.edu"}),
    url(r'^accounts/reset/done/?$', 'django.contrib.auth.views.password_reset_done'),
    url(r'^accounts/reset/confirm/(?P<uidb36>[0-9A-Za-z]+)-(?P<token>.+)', 'django.contrib.auth.views.password_reset_confirm'),
    url(r'^accounts/reset/complete/?$', 'django.contrib.auth.views.password_reset_complete'),
)
