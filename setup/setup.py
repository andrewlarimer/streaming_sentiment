import setuptools

setuptools.setup(
    name='vaderDF',
    version='1',
    install_requires=['google-cloud-core','google-cloud-logging'],
    packages=setuptools.find_packages(),
    include_package_data=True
)
