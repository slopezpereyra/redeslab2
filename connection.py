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
    VALID_CHARS,
    error_messages,
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

    def is_valid_filename(self, filename: str) -> bool:
        if not filename:
            return False
        if "/" in filename or "\\" in filename:
            return False
        if ".." in filename:
            return False
        return all(ch in VALID_CHARS for ch in filename)

    def handle(self) -> None:
        """
        Atiende eventos de la conexión hasta que termina.
        """
        try:
            while self.connected:
                while EOL not in self.buffer and self.connected:
                    # recv() puede devolver datos parciales, los acumulamos
                    data = self.socket.recv(4096).decode("ascii")
                    if not data:
                        # Si recv devuelve vacío, el cliente cerró la conexión
                        self.connected = False
                        break
                    self.buffer += data
                    if "\n" in self.buffer and EOL not in self.buffer:
                        # Hay un \n suelto sin \r en el buffer: error fatal 100
                        self.send_response(BAD_EOL)
                        self.connected = False
                        break

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
        finally:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
                self.socket.close()
            #parte F que no rompa nada
    def handle_get_slice(self, args: list[str]) -> None:
        """
        Parte F: Envío de fragmentos de archivos.
        Uso: get_slice <filename> <offset> <size> [mode]
        """
        # Validamos cantidad de argumentos
        if len(args) < 3 or len(args) > 4:
            self.send_response(INVALID_ARGUMENTS)
            return

        try:
            filename = args[0]
            filepath = os.path.join(self.directory, filename)
            offset = int(args[1])
            size = int(args[2])
            # Si no hay 4to argumento, por base64
            mode = args[3] if len(args) == 4 else 'base64'

            # Verificamos si el archivo existe
            if not os.path.isfile(filepath):
                self.send_response(FILE_NOT_FOUND)
                return

            file_size = os.path.getsize(filepath)
            # Validamos que el offset y size no se pasen del archivo
            if offset < 0 or size < 0 or (offset + size) > file_size:
                self.send_response(BAD_OFFSET)
                return

            # Leemos los bytes solicitados
            with open(filepath, "rb") as f:
                f.seek(offset)
                data = f.read(size)

            if mode == 'base64':
                self.send_response(CODE_OK)
                encoded = b64encode(data)
                # En base64 mandamos los datos + el EOL del protocolo
                self.socket.sendall(encoded + EOL.encode("ascii"))

            elif mode == 'raw':
                self.send_response(CODE_OK)
                # Framing para RAW: header + linea vacia + Bytes
                header = f"{CONTENT_LENGTH_PREFIX} {len(data)}{EOL}{EOL}"
                self.socket.sendall(header.encode("ascii") + data)

            else:
                # intentamos solucionar 203 /= 201
                self.send_response(INVALID_ARGUMENTS)

        except (ValueError, IndexError):
            self.send_response(INVALID_ARGUMENTS)
        except Exception:
            self.send_response(INTERNAL_ERROR)

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

        cmd = args[0]

        if cmd not in COMMANDS:
            self.send_response(INVALID_COMMAND)
            return

        # Dispatch a handlers reduciendo la complejidad por función.
        if cmd == "quit":
            self._handle_quit(args)
        elif cmd == "help":
            self._handle_help(args)
        elif cmd == "get_file_listing":
            self._handle_get_file_listing(args)
        elif cmd == "get_metadata":
            self._handle_get_metadata(args)
        elif cmd == "get_slice":
            self._handle_get_slice(args)
        else:
            self.send_response(INVALID_COMMAND)

    def _handle_quit(self, args: list[str]) -> None:
        if len(args) != 1:
            self.send_response(INVALID_ARGUMENTS)
            return
        self.send_response(CODE_OK)
        self.connected = False

    def _handle_help(self, args: list[str]) -> None:
        if len(args) != 1:
            self.send_response(INVALID_ARGUMENTS)
            return
        payload = ""
        for command in COMMANDS:
            payload += command + EOL
        payload += EOL
        self.send_response(CODE_OK, payload)

    def _handle_get_file_listing(self, args: list[str]) -> None:
        if len(args) != 1:
            self.send_response(INVALID_ARGUMENTS)
            return
        payload = ""
        try:
            for f in os.listdir(self.directory):
                payload += f + EOL
        except OSError:
            self.send_response(INTERNAL_ERROR)
            return
        payload += EOL
        self.send_response(CODE_OK, payload)

    def _handle_get_metadata(self, args: list[str]) -> None:
        if len(args) != 2:
            self.send_response(INVALID_ARGUMENTS)
            return
        filename = args[1]
        if not self.is_valid_filename(filename):
            self.send_response(INVALID_ARGUMENTS)
            return
        filepath = os.path.join(self.directory, filename)
        try:
            size = os.path.getsize(filepath)
        except PermissionError:
            self.send_response(INTERNAL_ERROR)
            return
        except OSError:
            self.send_response(FILE_NOT_FOUND)
            return
        self.send_response(CODE_OK, f"{size}{EOL}")

    def _handle_get_slice(self, args: list[str]) -> None:
        if len(args) < 4 or len(args) > 5:
            self.send_response(INVALID_ARGUMENTS)
            return
        filename = args[1]
        if not self.is_valid_filename(filename):
            self.send_response(INVALID_ARGUMENTS)
            return
        filepath = os.path.join(self.directory, filename)
        try:
            offset = int(args[2])
            size = int(args[3])
        except ValueError:
            self.send_response(INVALID_ARGUMENTS)
            return
        if offset < 0 or size < 0:
            self.send_response(INVALID_ARGUMENTS)
            return
        try:
            file_size = os.path.getsize(filepath)
        except PermissionError:
            self.send_response(INTERNAL_ERROR)
            return
        except OSError:
            self.send_response(FILE_NOT_FOUND)
            return
        mode = args[4] if len(args) == 5 else 'base64'
        if mode not in ['base64', 'raw']:
            self.send_response(INVALID_ARGUMENTS)
            return
        if (offset + size) > file_size:
            self.send_response(BAD_OFFSET)
            return
        try:
            with open(filepath, "rb") as f:
                f.seek(offset)
                data = f.read(size)
        except PermissionError:
            self.send_response(INTERNAL_ERROR)
            return
        except OSError:
            self.send_response(FILE_NOT_FOUND)
            return
        if mode == 'base64':
            encoded_data = b64encode(data).decode("ascii")
            payload = f"{encoded_data}{EOL}"
            self.send_response(CODE_OK, payload)
            return
        # raw mode
        self.send_response(CODE_OK)
        header = f"{CONTENT_LENGTH_PREFIX} {len(data)}{EOL}{EOL}"
        self.socket.sendall(header.encode("ascii") + data)


