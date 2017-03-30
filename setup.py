from setuptools import setup

setup(
    name='datacube-stats',
    version='0.3b2',
    packages=['datacube_stats'],
    url='https://github.com/data-cube/',
    license='Apache',
    author='Geosience Australia',
    author_email='datacube@ga.gov.au',
    description='Perform statistics operations on a Data Cube',
    install_requires=['xarray', 'click', 'pandas', 'numpy', 'datacube', 'rasterio',],
    setup_requires=['pytest-runner'],
    tests_require=['pytest', 'mock'],
    entry_points={
        'console_scripts': [
            'datacube-stats = datacube_stats.main:main'
        ],
        'datacube.stats': [
            'wofs-summary = datacube_stats.statistics:WofsStats'
        ]
    },
)
