from importlib.util import find_spec


def test_application_factory_exists():
    assert find_spec('helpdesk') is not None, 'Application package not implemented'
    from helpdesk import create_app
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://'})
    assert app.test_client().get('/health').status_code == 200
