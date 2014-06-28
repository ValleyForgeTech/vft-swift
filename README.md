vft-swift
=========

Prerequisites
-------------

 * [Python 2.7](https://www.python.org/)
 * [pip](http://pip.readthedocs.org/en/latest/installing.html)

Installation
------------

Install virtualenv using pip

```
$ pip install virtualenv
```

Clone the vft-swift repo

```
$ git clone git@github.com:ValleyForgeTech/vft-swift.git
$ cd vft-swift
```

Create a virtual environment

```
$ virtualenv venv
```

Activate your virtual environemtn

```
$ source venv/bin/activate
```

Install the project requirements

```
$ pip install -r requirements.txt
```

Deploying the Swift Cluster to EC2
---------

Update the following blanks with your EC2 credentials

```
my_access_key = ''
my_secret_access_key = ''
```

To execute, run the following command

```
$ fab build_swift_cluster
```

Copy the rysyncd.conf file to your directory

Testing
-------

```
$ swift -A http://<YOUR_EC2_IP>:8080/auth/v1.0 -U test:tester -K testing stat
$ swift -A http://<YOUR_EC2_IP>:8080/auth/v1.0/ -U test:tester -K testing upload test2 *.txt
$ swift -A http://<YOUR_EC2_IP>:8080/auth/v1.0/ -U test:tester -K testing list
$ swift -A http://<YOUR_EC2_IP>:8080/auth/v1.0/ -U test:tester -K testing list test2
```
