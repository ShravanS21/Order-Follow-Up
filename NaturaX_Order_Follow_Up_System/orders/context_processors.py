from .views import build_app_context

def app_context(request):
    return build_app_context(request)
