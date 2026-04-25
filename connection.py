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

        # TODO-list (Etapa E - Errores y robustez):
        # 1. Validación de rutas seguras: Asegurarse de que el argumento FILENAME no contenga caracteres inválidos ni secuencias de escape (ej. '../') para evitar vulnerabilidades de Path Traversal. Puedes apoyarte del set de caracteres válidos (`VALID_CHARS`) importado de `constants.py`. Ante una ruta maliciosa o caracteres incorrectos, devolver INVALID_ARGUMENTS.
        # 2. Tipado de argumentos: Envolver las conversiones enteras como `int(args[2])` en el comando `get_slice` en bloques `try...except ValueError`. Si fallan debido a letras, devolver código INVALID_ARGUMENTS.
        # 3. Errores del sistema de archivos: Envolver en `try...except OSError` la llamada a `os.listdir()` y cualquier apertura de archivo (`open`). Si el archivo no tiene permisos de lectura, devolver el código INTERNAL_ERROR (199).
        
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
            try:
                for f in os.listdir(self.directory):
                    payload += f + EOL
            except OSError:
                self.send_response(INTERNAL_ERROR)
                return
            payload += EOL
            self.send_response(CODE_OK, payload)

        elif cmd == "get_metadata":
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

        elif cmd == "get_slice":
            # Esperamos entre 4 y 5 argumentos: get_slice FILENAME OFFSET SIZE [raw]
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

            if (offset + size) > file_size:
                self.send_response(BAD_OFFSET)
                return

            try:
                with open(filepath, "rb") as f:  # rb -> en binario
                    f.seek(offset)
                    data = f.read(size)
            except PermissionError:
                self.send_response(INTERNAL_ERROR)
                return
            except OSError:
                self.send_response(FILE_NOT_FOUND)
                return

            # NO SE PASA `raw` así que devolvemos el slice codificado en base64.
            if len(args) == 4:
                encoded_data = b64encode(data).decode("ascii")
                payload = f"{encoded_data}{EOL}"
                self.send_response(CODE_OK, payload)
            
            # Dejamos preparado el esqueleto para la Etapa D (raw)
            # TODO-list (Etapa D):
            # 1. Verificar si el 4to argumento coincide exactamente con la cadena "raw".
            # 2. Si es distinto de "raw" (ej. "rawx"), responder con un código de error (por ejemplo, INVALID_ARGUMENTS).
            # 3. Si es "raw", no enviar este string "Me pediste raw...". Responder primero con "0 OK\r\n".
            # 4. Enviar la cabecera: "Content-Length: <SIZE>\r\n" seguida de una línea vacía ("\r\n").
            # 5. Enviar los <SIZE> bytes crudos leídos del archivo directamente a traves del socket (no usar base64 ni appendear EOL a los datos binarios).
            
            
            elif len(args) == 5:
                if args[4] == "raw":
                    self.send_response(CODE_OK)
                    content_length_header = f"{CONTENT_LENGTH_PREFIX}{size}{EOL}"
                    self.socket.sendall(content_length_header.encode("ascii"))
                    self.socket.sendall(EOL.encode("ascii"))  # Línea vacía
                    self.socket.sendall(data)
                else:
                    self.send_response(INVALID_ARGUMENTS)


