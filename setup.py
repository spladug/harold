from setuptools import setup, find_packages

setup(
    name="harold",
    version="1.0",
    author="Neil Williams",
    author_email="neil@spladug.net",
    url="https://github.com/spladug/harold",
    include_package_data=True,
    zip_safe=False,
    packages=find_packages(),
    install_requires=[
        "Twisted>=11.1.0",
        "SQLAlchemy",
    ],
    extras_require={
        "salon": [
            "Flask>=0.10",
            "Flask-SQLAlchemy>=0.16",
            "requests>=1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "harold-register-webhooks = harold.webhooks:main",
            "salon-sync = salon.sync:main [salon]",
        ],
    },
    data_files=[
        ("/usr/local/sbin/", [
            "harold.tac",
        ]),
        ("/etc/init/", [
            "upstart/harold.conf",
            "upstart/harold-startup.conf",
        ]),
        ("/etc/harold.d/", [
            "README.md",
        ]),
        ("/var/www", [
            "salon/misc/no-cert.html",
        ]),
    ],
)
