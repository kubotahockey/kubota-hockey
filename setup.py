from setuptools import setup, find_packages

setup(
      name = "KubotaWeb",
      version = '0.1',
      packages = find_packages(),
      install_requires=[
          'Flask>=1.1.2',
          'flask_login',
          'pandas',
          'numpy',
          'stripe',
          'gunicorn',
          ],
      author = 'Brennan',
      author_email= 'kubotahockey@outlook.com',
      description= 'A web application for Kubota Website',
      url= 'https://github.com/kubotahockey/kubota-hockey',
      classifiers=[
          'Programming Language:: Python :: 3',
          'License :: OSI Approved :: MIT License',
          'Operating System :: OS Independent',
          ],
      python_requires = '>=3.6'
      )
