# coding: utf-8
from setuptools import setup
import os


README = os.path.join(os.path.dirname(__file__), 'README.rst')

setup(name='python-decouple-improved',
      version='3.9',
      description='Strict separation of settings from code. (Improved)',
      long_description=open(README).read(),
      author="Henrique Bastos, Arun Aruljothi", author_email="henrique@bastos.net, arun@arunaruljothi.com",
      license="MIT",
      py_modules=['decouple'],
      zip_safe=False,
      platforms='any',
      include_package_data=True,
      classifiers=[
          'Development Status :: 5 - Production/Stable',
          'Framework :: Django',
          'Framework :: Flask',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: MIT License',
          'Natural Language :: English',
          'Operating System :: OS Independent',
          'Programming Language :: Python',
          'Programming Language :: Python :: 3',
          'Topic :: Software Development :: Libraries',
      ],
      url='http://github.com/henriquebastos/python-decouple/',)
