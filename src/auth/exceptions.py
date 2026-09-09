class AuthException(Exception):
    pass

class EmailAlreadyRegistered(AuthException):
    def __init__(self, email: str):
        self.email = email
        super().__init__(f"Email {email} is already registered")

class InvalidCredentials(AuthException):
    def __init__(self):
        super().__init__("Invalid credentials")
