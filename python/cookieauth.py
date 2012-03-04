"""
This module provides an example of functions used to mint and validate an
authenticator for use in a cookie-based web authentication scheme. It is based
on suggestions and techniques described in MIT Technical Report 818, "The Dos
and Don'ts of Client Authentication on the Web," which can be found at
http://cookies.lcs.mit.edu/

The authenticator is a cookie value that contains the username, an optional
expiration, and a HMAC-SHA digest of these parameters. For example:

  username=mrf&exp=1167812404&digest=66bb54794e71547bd46a048236d485a3aea5e6af
  
An authenticator with no expiration:

>>> mint('anotsosecuresecret','mrf')
'username=mrf&digest=4147fa8fee492ae699d73a18691f07eb24bd2d8b'

The HMAC-SHA algorithm is a non-malleable MAC, so it should not be feasible for
an attacker to forge a valid authenticator if the attacker only has samples
of valid authenticators.

Of course, the security of the scheme depends upon the choice of a suitable key
that cannot be easily guessed with a dictionary attack and is long enough to
make a brute force attack impractical.

Despite the fact that a valid authenticator cannot be forged, the scheme is
vulnerable to a reply attack if the cookie is transmitted by an non-secure
transport. (Of course the password is also vulnerable to an evesdropping
adversary if it is submitted in the clear from the login form.) Specifying the
lifetime when the authenticator is minted reduces the exposure to this kind of
attack because the cookie will automatically expire at some specific time in the
future.

If HTTPS is used to secure the submit from the login form, then the cookie
should be issued with the secure attribute set. This is necessary to prevent the
authenticator being inadvertently divulged to an evesdropping adversary when an
authenticated user vists a non-secure page on the website. If personalization or
some other application feature requires knowledge of the user's identity on the
non-secure pages, then the application should issue a second, non-secure cookie
(minted using a different secret key) for use with these low-risk portions of
the website.


Copyright (c) 2007 Matthew Fremont
"""

import hmac
import sha
import time

EXP_KEY = 'exp='
USERNAME_KEY = 'username='
DIGEST_KEY = 'digest='
SEP = '&'
    
def mint(secretkey,username,lifetime=None):
    """
    Returns a cookie value suitable for use as an authenticator for the user
    specified by the string username. The string secretkey is used as the key
    to generate the HMAC-SHA digest.
    
    Raises ValueError if username contains any non-permissable characters.
    Currently, the only character not allowed is the ampersand.

>>> mint('anotsosecuresecret','mrf&exp')
Traceback (most recent call last):
  File "<stdin>", line 1, in ?
  File "cookieauth.py", line 67, in mint
    raise ValueError, "username cannot contain ampersand character"
ValueError: username cannot contain ampersand character

    The lifetime parameter is used to specify how many seconds from now the
    authenticator will expire. This limits the vulnerability of the sytem to a
    replay attack because it prevents an attacker from using an old
    authenticator to gain access. If lifetime isn't specified, the authenticator
    is valid indefinitely.
    
    Raises ValueError if lifetime cannot be converted to an integer:

>>> mint('anotsosecuresecret','mrf','foo')
Traceback (most recent call last):
  File "<stdin>", line 1, in ?
  File "cookieauth.py", line 91, in mint
    expiration = int(time.time()) + int(lifetime)
ValueError: invalid literal for int() with base 10: 'foo'

    The cookie itself should be issued as a transient cookie. If the login
    exchange is performed via HTTPS, the cookie should also be marked as secure
    so that the client will only transmit the cookie for subsequent HTTPS
    requests.
    """
    if username.find(SEP) >= 0:
        raise ValueError, "username cannot contain ampersand character"
        
    cookieval = USERNAME_KEY + username
    if (lifetime):
        expiration = int(time.time()) + int(lifetime)
        cookieval += SEP + EXP_KEY + str(expiration)
    mac = hmac.new(secretkey,cookieval,sha)
    cookieval += SEP + DIGEST_KEY + mac.hexdigest()
    return cookieval
    
def validate(secretkey,cookieval):
    """
    Returns the username if the cookieval is a valid authenticator issued by the
    mint() function, or None otherwise. The authenticator should be the full
    text of the cookie value issued by mint(). The string secretkey is used as
    the key to generate the HMAC-SHA digest, and should be the same key
    orginally used to mint the authenticator.
    
    >>> c = mint('anotsosecuresecret','mrf',600)
    >>> validate('anotsosecuresecret',c)
    'mrf'
    
    The authenticator could be invalid because it has been tampered with:
    
    >>> c = mint('anotsosecuresecret','mrf')
    >>> validate('anotsosecuresecret',c.replace('mrf','admin'))

    The expiration time has been reached:

    >>> import time
    >>> c = mint('anotsosecuresecret','mrf',lifetime=10)
    >>> validate('anotsosecuresecret',c)
    'mrf'
    >>> time.sleep(5)
    >>> validate('anotsosecuresecret',c)
    'mrf'
    >>> time.sleep(7)
    >>> validate('anotsosecuresecret',c)
        
    Or it is a forgery.
    """
    try:
        (msg, digest) = cookieval.split(SEP + DIGEST_KEY,1)
        mac = hmac.new(secretkey,msg,sha)
        if digest == mac.hexdigest():
            # valid authenticator. check expiration, then extract username
            expks = msg.find(EXP_KEY)
            if expks > -1:
                expve = msg.find(SEP,expks)
                if expve == -1: expve = len(msg)
                exp = int(msg[expks+len(EXP_KEY):expve])
                if time.time() >= exp:
                    # authenticator has expired
                    return None
            uks = msg.find(USERNAME_KEY)
            if uks > -1:
                uve = msg.find(SEP,uks)
                if uve == -1: uve = len(msg)
                return msg[uks+len(USERNAME_KEY):uve]
    except:
        pass
    # validation failed or username parameter was not present in cookie
    return None


if __name__ == "__main__":
    import doctest
    doctest.testmod()
