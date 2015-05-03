import base64

from apps.credentials.models import (
    OAuthClient,
    OAuthUser,
)
from apps.tokens.models import (
    OAuthAuthorizationCode,
    OAuthAccessToken,
    OAuthRefreshToken,
)
from proj.exceptions import (
    GrantTypeRequiredException,
    InvalidGrantTypeException,
    CodeRequiredException,
    UsernameRequiredException,
    PasswordRequiredException,
    RefreshTokenRequiredException,
    AccessTokenRequiredException,
    InvalidAccessTokenException,
    ExpiredAccessTokenException,
    InsufficientScopeException,
    ClientCredentialsRequiredException,
    InvalidClientCredentialsException,
    InvalidUserCredentialsException,
    AuthorizationCodeNotFoundException,
    RefreshTokenNotFoundException,
)


def authentication_required(scope):
    def _method_wrapper(view):

        def _check_access_token_in_header(request):
            if not 'HTTP_AUTHORIZATION' in request.META:
                return False

            # Only Bearer tokens are supported for now
            auth_method, auth = request.META['HTTP_AUTHORIZATION'].split(' ')
            if auth_method.lower() != 'bearer':
                return False

            return auth

        def _check_access_token_in_post(request):
            if 'access_token' not in request.POST:
                return False

            return request.POST['access_token']

        def _check_access_token_in_get(request):
            if 'access_token' not in request.GET:
                return False

            return request.GET['access_token']

        def _arguments_wrapper(request, *args, **kwargs):
            access_token = _check_access_token_in_header(request=request)
            if not access_token:
                access_token = _check_access_token_in_post(request=request)
            if not access_token:
                access_token = _check_access_token_in_get(request=request)
                
            if not access_token:
                raise AccessTokenRequiredException()

            try:
                access_token = OAuthAccessToken.object.get(
                    access_token=access_token)
            except OAuthAccessToken.DoesNotExist:
                raise InvalidAccessTokenException()

            if access_token.is_expired():
                raise ExpiredAccessTokenException()

            if scope not in access_token.scope:
                raise InsufficientScopeException()

            request.access_token = access_token
            return view(request, *args, **kwargs)

        return _arguments_wrapper

    return _method_wrapper


def validate_request(view):
    """
    Validates that request contains all required data
    :param view:
    :return: _wrapper
    """

    def _validate_grant_type(request):
        """
        Checks grant_type parameter and also performs checks on additional
        parameters required by specific grant types.
        Assigns grant_type to the request so we can use it later.

        Also optionally assigns other objects based on specific grant such
        as user, auth_code and refresh_token
        :param request:
        :return:
        """

        grant_type = request.POST.get('grant_type', None)

        if not grant_type:
            raise GrantTypeRequiredException()

        valid_grant_types = (
            'client_credentials',
            'authorization_code',
            'password',
            'refresh_token',
        )
        if grant_type not in valid_grant_types:
            raise InvalidGrantTypeException()

        # authorization_code grant requires code parameter
        if grant_type == 'authorization_code':
            try:
                auth_code = request.POST['code']
            except KeyError:
                try:
                    auth_code = request.GET['code']
                except KeyError:
                    raise CodeRequiredException()

        # password grant requires username and password parameters
        if grant_type == 'password':
            try:
                username = request.POST['username']
            except KeyError:
                try:
                    username = request.GET['username']
                except KeyError:
                    raise UsernameRequiredException()
            try:
                password = request.POST['password']
            except KeyError:
                try:
                    password = request.GET['password']
                except KeyError:
                    raise PasswordRequiredException()

        # refresh_token grant requires refresh_token parameter
        if grant_type == 'refresh_token':
            try:
                refresh_token = request.POST['refresh_token']
            except KeyError:
                try:
                    refresh_token = request.GET['refresh_token']
                except KeyError:
                    raise RefreshTokenRequiredException()

        if grant_type == 'authorization_code':
            try:
                request.auth_code = OAuthAuthorizationCode.objects.get(
                    code=auth_code)
            except OAuthAuthorizationCode.DoesNotExist:
                raise AuthorizationCodeNotFoundException()

        if grant_type == 'password':
            try:
                user = OAuthUser.objects.get(email=username)
            except OAuthUser.DoesNotExist:
                raise InvalidUserCredentialsException()

            if not user.verify_password(password):
                raise InvalidUserCredentialsException()

            request.user = user

        if grant_type == 'refresh_token':
            try:
                request.refresh_token = OAuthRefreshToken.objects.get(
                    refresh_token=refresh_token)
            except OAuthRefreshToken.DoesNotExist:
                raise RefreshTokenNotFoundException()

        request.grant_type = grant_type

    def _extract_client(request):
        """
        Tries to extract client_id and client_secret from the request.
        It first looks for Authorization header, then tries POST data.
        Assigns client object to the request for later use.
        :param request:
        :return:
        """
        client_id, client_secret = None, None

        # First, let's check Authorization header if present
        if 'HTTP_AUTHORIZATION' in request.META:
            auth_method, auth = request.META['HTTP_AUTHORIZATION'].split(': ')
            if auth_method.lower() == 'basic':
                client_id, client_secret = base64.b64decode(auth).split(':')

        # Fallback to POST and then to GET
        if not client_id or not client_secret:
            try:
                client_id = request.POST['client_id']
                client_secret = request.POST['client_secret']
            except KeyError:
                try:
                    client_id = request.GET['client_id']
                    client_secret = request.GET['client_secret']
                except KeyError:
                    raise ClientCredentialsRequiredException()

        # Check client exists
        try:
            client = OAuthClient.objects.get(client_id=client_id)
        except OAuthClient.DoesNotExist:
            raise InvalidClientCredentialsException()

        # And that client secret is correct
        if not client.verify_password(client_secret):
            raise InvalidClientCredentialsException()

        request.client = client

    def _wrapper(request, *args, **kwargs):
        _validate_grant_type(request=request)
        _extract_client(request=request)

        return view(request, *args, **kwargs)

    return _wrapper
