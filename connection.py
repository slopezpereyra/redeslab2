# encoding: utf-8
# Revisión 2019 (a Python 3 y base64): Pablo Ventura
# Copyright 2014 Carlos Bederián
# $Id: connection.py 455 2011-05-01 00:32:09Z carlos $

import socket
import os 
from base64 import b64encode

from constants import (
    BAD_EOL,
    BAD_OFFSET,
    BAD_REQUEST,
    CODE_OK,
    COMMANDS,
    CONTENT_LENGTH_PREFIX,
    EOL,
    FILE_NOT_FOUND,
    INTERNAL_ERROR,
    INVALID_ARGUMENTS,
    INVALID_COMMAND,
    error_messages,
    fatal_status,
)


class Connection:
    """
    Conexión punto a punto entre el servidor y un cliente.
    Se encarga de satisfacer los pedidos del cliente hasta
    que termina la conexión.
    """

    def __init__(self, sock: socket.socket, directory: str) -> None:
        self.socket = sock
        self.directory = directory
        # Un buffer para acumular lo que llega por la red
        self.buffer = ""
        self.connected = True

    def send_response(self, code: int, payload: str = "") -> None:
        """
        Función auxiliar para no repetir código. 
        Arma la línea de respuesta: <código> <mensaje>\r\n + payload
        """
        response = f"{code} {error_messages[code]}{EOL}{payload}"
        self.socket.sendall(response.encode("ascii"))

    def handle(self) -> None:
        """
        Atiende eventos de la conexión hasta que termina.
        """
        while self.connected:
            while EOL not in self.buffer and self.connected:
                # recv() puede devolver datos parciales, los acumulamos
                data = self.socket.recv(4096).decode("ascii")
                if not data:
                    # Si recv devuelve vacío, el cliente cerró la conexión
                    self.connected = False
                    break
                self.buffer += data

            if not self.connected:
                break

            # split(EOL, 1) corta en el primer \r\n que encuentra
            line, self.buffer = self.buffer.split(EOL, 1)

            if '\n' in line:
                # Hay un \n suelto sin \r, esto es un error 100
                self.send_response(BAD_EOL)
                self.connected = False
                break

            self.process_command(line)


    def process_command(self, line: str) -> None:
        """
        Interpreta el comando enviado por el cliente y ejecuta la acción.
        """
        args = line.split()
        
        # Si la línea estaba vacía (mandaron solo \r\n) args queda vacío -> Error 101
        if not args:
            self.send_response(BAD_REQUEST)
            self.connected = False
            return

        # Ahora un parseo al estilo de cuando en SO hicimos parsing para
        # los cmds de la command line.
        cmd = args[0]

        if cmd not in COMMANDS:
            self.send_response(INVALID_COMMAND)
            return

        if cmd == "quit":
            if len(args) != 1:
                self.send_response(INVALID_ARGUMENTS)
                return
            self.send_response(CODE_OK)
            self.connected = False

        elif cmd == "help":
            if len(args) != 1:
                self.send_response(INVALID_ARGUMENTS)
                return
            payload = ""
            for command in COMMANDS:
                payload += command + EOL
            payload += EOL  # El protocolo pide una línea vacía al final
            self.send_response(CODE_OK, payload)

        elif cmd == "get_file_listing":
            if len(args) != 1:
                self.send_response(INVALID_ARGUMENTS)
                return
            payload = ""
            # usamos os.listdir para leer el directory
            for f in os.listdir(self.directory):
                payload += f + EOL
            payload += EOL
            self.send_response(CODE_OK, payload)

        elif cmd == "get_metadata":
            if len(args) != 2:
                self.send_response(INVALID_ARGUMENTS)
                return
            
            filename = args[1]
            filepath = os.path.join(self.directory, filename)
            
            if not os.path.exists(filepath):
                self.send_response(FILE_NOT_FOUND)
                return
            
            size = os.path.getsize(filepath)
            payload = f"{size}{EOL}"
            self.send_response(CODE_OK, payload)

        elif cmd == "get_slice":
            # ETAPA B nos pide una respuesta provisoria,
            # meto mensaje random de que está todo okay.
            self.send_response(CODE_OK, f"Todo bien en get slice!{EOL}")
