vft-swift
=========

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

```bash
$ swift -A http://<YOUR_EC2_IP>:8080/auth/v1.0 -U test:tester -K testing stat
$ swift -A http://<YOUR_EC2_IP>:8080/auth/v1.0/ -U test:tester -K testing upload test2 *.txt
$ swift -A http://<YOUR_EC2_IP>:8080/auth/v1.0/ -U test:tester -K testing list
$ swift -A http://<YOUR_EC2_IP>:8080/auth/v1.0/ -U test:tester -K testing list test2
```
