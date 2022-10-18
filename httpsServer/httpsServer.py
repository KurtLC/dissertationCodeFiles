#import statements
from datetime import datetime as dt #import methods from the datetime module [https://docs.python.org/3/library/datetime.html]
from os import getcwd as cwd, mkdir #import methods from the built-in os module [https://docs.python.org/3/library/os.html]
from json import dumps as jsndumps #import methods from the json module [https://docs.python.org/3/library/json.html]
from http.server import HTTPServer, BaseHTTPRequestHandler #import methods from the http.server module [https://docs.python.org/3/library/http.server.html]
from ssl import SSLContext, PROTOCOL_TLS_SERVER #mport methods from the ssl module [https://docs.python.org/3/library/ssl.html]
from socketserver import BaseServer #import a method from the socketserver server [https://docs.python.org/3/library/socket.html]


#server-related variables
hostname = "192.168.5.9" #define hostname IP to be used for the server
port = 8443 #define port number to be used for the server

#logfile-related variables
logfolder = "HassLogfiles" #define the logfile folder name
logfolderpath = cwd()+"\\"+logfolder+"\\" #define the logfile folder path relative to the current working directory (CWD)
logfilename = "logs_"+dt.now().strftime('%d-%m-%Y')+".log" #define the logfile file name
filepath = logfolderpath+logfilename #define the logfile file path

#certificate-related variables
certfolder = cwd()+"\\certificate\\" #define certificate-related files' folder path relative to the CWD
certpath = certfolder+"CA.pem" #define the Certificate Signing Request (CSR) file path
keypath = certfolder+"CA.key" #define key file path


#define the request handler class for the server using HTTP protocol
class httpServer(BaseHTTPRequestHandler):
    #handle GET requests
    def do_GET(self):
        #set webpage headers
        self.send_header("Content-type", "text/html")
        #close webpage headers section
        self.end_headers()

    #handle POST requests
    def do_POST(self):
        #the IP of the client connecting to the server
        clientIP = self.client_address[0]
        #parse the HTTP request headers
        data = int(self.headers['Content-Length'])
        #read and decode the data received
        data = self.rfile.read(data).decode('utf-8', 'ignore')
        #convert the data received from JSON to String and then cleanup said String
        data = jsndumps(data).replace("{","").replace("}","").replace("\"","").replace("\\","")
        #string specifying which host sent the data, at what time it was received, & the actual data that reached the server 
        dataRecMsg = (f"Data received from host {clientIP} at {dt.now().strftime('%H:%M:%S')} -\n{data}\n")
        #inform user of the data received along with the related details specified by the 'dataRecMsg' string
        print(dataRecMsg)
        #append to the logfile the data received along with the related details specified by the 'dataRecMsg' string
        logfile.write(f"\n{dataRecMsg}")


#execute the code if the file was invoked directly
if __name__ == "__main__":
    #run the program
    try:
        #inform user that the server is starting
        print("\nSTARTING SERVER...\n\n")
        #create an HTTP server instance listening on the predefined hostname and port
        server = HTTPServer((hostname, port), httpServer)

        #create an SSLContext instance to pass the server protocol to be used
        sslcontext = SSLContext(protocol=PROTOCOL_TLS_SERVER)
        #load the private key and the corresponding certificate to the previously created SSLContext
        sslcontext.load_cert_chain(certfile=certpath, keyfile=keypath)
        #wrap the server's socket using the previously created SSLContext to secure/encrypt its HTTP connection
        server.socket = sslcontext.wrap_socket(server.socket, server_side=True)

        #logfile folder directory
        try:
            #Create target file directory
            mkdir(logfolderpath) #Create a directory based on 'path'
            #if file directory does not exist
            print(f"\"{logfolder}\" folder created successfully in current directory | Writing to file \"{logfilename}\"\n")
        except FileExistsError: #exception raised when trying to create a file directory which already exists
            #if file directory already exists
            print(f"\"{logfolder}\" folder already exists in current directory | Writing to file \"{logfilename}\"\n")

        #create and write/append the data received to the logfile
        logfile = open(filepath, "a", buffering=1) #buffering enabled to save after each line rather than when the program ends to prevent data loss

        #string specifying that the server started, on which date and at what time, & to which hostname & port its bound to
        serverstartMsg = (f"\n********** SERVER STARTED [{dt.now().strftime('%d-%m-%Y %H:%M:%S')}] **********\n\nServer running on https://{hostname}:{port}\n\n")
        #inform the user that the server session has been started
        print(serverstartMsg)
        #append to logfile that the server  session has been started
        logfile.write(serverstartMsg)    

        #server connection
        try:
            #run the server indefinitely unless the program is interrupted
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt: #catch any Keyboard Interrupt (such as ctrl+c)
            #shutdown the server
            server.shutdown()
            #close and cleanup the server session
            server.server_close()
            #string specifying that the server closed, & on which date and at what time
            servercloseMsg = (f"\n********** SERVER CLOSED [{dt.now().strftime('%d-%m-%Y %H:%M:%S')}] **********\n")
            #inform the user that the server session has been closed
            print(servercloseMsg)
            #append to the logfile that the server session has been closed
            logfile.write(f"\n{servercloseMsg}\n")

        #close/stop appending to the logfile
        logfile.close()

    except OSError as e: #catch any OS-based errors, particularly if the server IP's network is not available
        print(f"\nThe following OSError has occurred -\n{e}") #inform the user that an error occurred, and what the error was

