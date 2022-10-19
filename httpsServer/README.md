# httpsServer #

*This folder contains the HTTPS Server code file along with the associated certificate files.*

---------------
## Folder Contents ##

* **httpsServer.py file:** the HTTPS web server code used for the Data Breach (proof of concept) attack. To run the server -
    * install Python;
    * open a command prompt (cmd) window;
    * navigate to he folder where the 'httpsServer.py' is stored;
    * run 'python httpsServer.py' from the cmd window to call the 'httpsServer.py' file and start the server.
<br />

* **[Certificate](https://github.com/KurtL33/dissertationCodeFiles/tree/main/httpsServer/certificate) folder:** contains two certificate-related files generated using the OpenSSL software library -
    * CA.key -> the private key for the HTTPS server's certificate;
    * CA.pem -> the certificate chain for the HTTPS server's certificate.
