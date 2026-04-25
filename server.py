#!/usr/bin/env python
# encoding: utf-8
# Revisión 2019 (a Python 3 y base64): Pablo Ventura
# Revisión 2014 Carlos Bederián
# Revisión 2011 Nicolás Wolovick
# Copyright 2008-2010 Natalia Bidart y Daniel Moisset
# $Id: server.py 656 2013-03-18 23:49:11Z bc $

import argparse
import socket
import sys
import connection
from constants import DEFAULT_ADDR, DEFAULT_DIR, DEFAULT_PORT
import threading 


# RICARDO DATIN: En este link se entiende todo:
# https://docs.python.org/3/howto/sockets.html

class Server:
    """
    El servidor, que crea y atiende el socket en la dirección y puerto
    especificados donde se reciben nuevas conexiones de clientes.
    """

    def __init__(
        self,
        addr: str = DEFAULT_ADDR,
        port: int = DEFAULT_PORT,
        directory: str = DEFAULT_DIR,
    ) -> None:
        print(f"Serving {directory} on {addr}:{port}.")

        # Creamos el socket TCP del servidor, lo vinculamos a la dirección y
        # puerto especificados y lo ponemos a escuchar. El socket se cierra
        # automáticamente al finalizar el programa.
        # Una vez más, revisar: https://docs.python.org/3/howto/sockets.html
        self.directory = directory 
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((addr, port))
        self.server_socket.listen()



    def serve(self) -> None:
        """
        Loop principal del servidor. Se acepta una conexión a la vez
        y se espera a que concluya antes de seguir.
        """
        while True:
            # dos notitas: (a) accept es bloqueante; (b) devuelve una tupla,
            # el nuevo socket para hablar con el cliente y la dirección del
            # cliente.
            client_socket, client_address = self.server_socket.accept()
            
            # TODO-list (Etapa F - Varios clientes/Hilos):
            # 1. Incluir la librería `threading` (o análoga) al comienzo del archivo.
            # 2. Modificar la atención paralela del socket: En lugar de bloquear el ciclo principal (loop del accept) llamando sincrónicamente a `conn.handle()`, delegar esta tarea.
            # 3. Crear (`threading.Thread`) y lanzar un subhilo individual por cada cliente conectado en donde la función objetivo (target) se encargue de `conn.handle()`.
            # 4. Ejecutar `.start()` sobre ese subhilo recién creado. Así, este hilo primario volverá instantáneamente al estado de bloqueo `accept()` para estar listo al recibir el siguiente intento de conexión sin esperas.

            conn = connection.Connection(client_socket, self.directory)
            thread = threading.Thread(target=conn.handle)
            thread.start()


def main() -> None:
    """Parsea los argumentos y lanza el server"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p", "--port",
        help="Número de puerto TCP donde escuchar",
        type=int,
        default=DEFAULT_PORT,
    )
    parser.add_argument(
        "-a", "--address",
        help="Dirección donde escuchar",
        default=DEFAULT_ADDR,
    )
    parser.add_argument(
        "-d", "--datadir",
        help="Directorio compartido",
        default=DEFAULT_DIR,
    )
    args = parser.parse_args()
    try:

        # TODO-list (Etapa G - Cierre y Red Tor):
        # 1. No se requiere código en backend para Tor por sí mismo, pero debes levantar el proxy SOCKS/Servicio Oculto mediante el archivo de reglas `torrc`, guiándote con el archivo `Guia_HFTP_Tor.md`.
        # 2. Prueba ejecutando el comando sin filtros: `python3 server-test.py` (debería pasar toda tu suite). 
        # 3. Comprueba tus métricas de entregas y código base sin errores ejecutando simplemente: `python3 grade.py` y verificando que apruebes el mínimo de cobertura y el validador ruff.

        server = Server(args.address, args.port, args.datadir)
        server.serve()
    except OSError as e:
        sys.stderr.write(f"Error al iniciar el servidor: {e}\n")
        sys.exit(1)


if __name__ == '__main__':
    main()
