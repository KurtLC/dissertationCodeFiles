# certificate #

*This folder contains the certificate files for the HTTPS Server.*
<br />

---------------
* The certificate files were generated using the **OpenSSL Toolkit** version 3.0.5 (*Installation for Windows: https://slproweb.com/download/Win64OpenSSL-3_0_5.exe*) **however this version is not recommended due to a recent vulnerability finding as per [CVE-2022-3602](https://nvd.nist.gov/vuln/detail/CVE-2022-3602)**.
<br />

*  To **generate the certificate** the following steps were followed -
    * install OpenSSL (*Guide: https://thesecmaster.com/procedure-to-install-openssl-on-the-windows-platform*)
    * open a command prompt (cmd) window as administrator;
    * navigate to the OpenSSL bin directory from the cmd window (*cd C:\Program Files\OpenSSL-Win64\bin*);
    * run the following command to generate the certificate with its attributes and private key:  
      *openssl req -x509 -newkey rsa:2048 -keyout CA.key -out CA.pem -sha256 -days 397 -nodes -subj "/C=US/ST=NY/L=Manhattan/O=Bonds Reliable/OU=Finance/CN=CA"*
<br />

* **Command breakdown** -
    *  openssl -> command-line tool installed and used to create certificates and the associated items (such as the private key)
    *  req -> 	specify requirements for the certificate
    *  x509 -> define the certificate context and layout
    *  newkey -> generate a new private key
    *  rsa -> define the RSA algorithm bit key length (2048 is used since it is widely supported)
    *  keyout -> create the .key file (preferably with the name of the domain)
    *  out -> generate the certificate (preferably with the name of the domain) - *in PEM format as specified by the ssl module documentation (https://docs.python.org/3/library/ssl.html)*
    *  sha -> the hashing algorithm to be used (sha256 is used since it is widely supported)
    *  days -> certificate set to expire after 397 days i.e. 13 months (industry-allowed maximum validity accounting for time zone differences)
    *  nodes -> specify that the certificate should not use a passphrase
    *  subj -> set certificate Subject attributes - *C = Country; ST = State; L = Locality; O = Organisation; OU = Organisational Unit; CN = Common Name*
