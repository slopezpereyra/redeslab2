#!/usr/bin/env python
# encoding: utf-8
# Revisión 2019 (a Python 3 y base64): Pablo Ventura
# Revisión 2011 Nicolás Wolovick
# Copyright 2008-2010 Natalia Bidart y Daniel Moisset
# $Id: server-test.py 388 2011-03-22 14:20:06Z nicolasw $

import logging
import os
import select
import shutil
import socket
import sys
import threading
import time
import unittest

import client
import constants
import connection

DATADIR = "testdata"
TIMEOUT = 3  # Segundos para esperar respuestas del servidor
# Conexión al servidor en pruebas (127.0.0.1: DEFAULT_ADDR 0.0.0.0 no es destino válido en muchos sistemas).
CONNECT_ADDR = "127.0.0.1"

# Los tests requieren el servidor HFTP corriendo en DEFAULT_ADDR:DEFAULT_PORT
# (ej.: python3 server.py -d testdata -p 19500).
# La suite completa (este archivo en el kickstart) es la misma que pueden usar
# para autoevaluarse antes de la entrega: `python3 server-test.py` sin filtros.
# Para tests + cobertura + métricas en un solo comando: `python3 grade.py`.
#
# Tests más lentos: test_big_file (~2MB), test_long_file_listing (200 archivos).
# El resto está acotado para que la suite corra en unos segundos.
# TestHFTPMultiClient exige varias conexiones concurrentes (p. ej. servidor con hilos).


class TestBase(unittest.TestCase):

    def setUp(self) -> None:
        print("\nIn method %s:" % self._testMethodName)
        shutil.rmtree(DATADIR, ignore_errors=True)
        os.makedirs(DATADIR, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(DATADIR, ignore_errors=True)
        if hasattr(self, "client"):
            if self.client.connected:
                logging.getLogger().setLevel(logging.CRITICAL)
                try:
                    self.client.close()
                except socket.error:
                    pass
                logging.getLogger().setLevel(logging.WARNING)
            del self.client
        if hasattr(self, "output_file"):
            if os.path.exists(self.output_file):
                os.remove(self.output_file)
            del self.output_file

    def new_client(self) -> client.Client:
        assert not hasattr(self, 'client')
        try:
            self.client = client.Client()
        except socket.error:
            self.fail("No se pudo establecer conexión al server")
        return self.client


class TestHFTPServer(TestBase):
    """Tests básicos del protocolo: conexión, listado, metadata, slices, retrieve."""

    # Tests
    def test_connect_and_quit(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect((constants.DEFAULT_ADDR, constants.DEFAULT_PORT))
        except socket.error:
            self.fail("No se pudo establecer conexión al server")
        s.send('quit\r\n'.encode("ascii"))
        # Le damos TIMEOUT segundos para responder _algo_ y desconectar
        w, _, __ = select.select([s], [], [], TIMEOUT)
        self.assertEqual(w, [s],
                         "Se envió quit, no hubo respuesta en %0.1f segundos" % TIMEOUT)
        # Medio segundo más par
        start = time.process_time()
        got = s.recv(1024)
        while got and time.process_time() - start <= 0.5:
            r, w, e = select.select([s], [], [], 0.5)
            self.assertEqual(r, [s], "Luego de la respuesta de quit, la "
                             "conexión se mantuvo activa por más "
                             "de 0.5 segundos")
            got = s.recv(1024)
        # Se desconectó?
        self.assertTrue(not got)
        s.close()

    def test_help(self) -> None:
        """El comando help devuelve 0 OK y la lista de comandos (uno por línea, fin con línea vacía)."""
        c = self.new_client()
        c.send("help")
        status, message = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.CODE_OK, "help debe responder 0 OK")
        lines = []
        while True:
            line = c.read_line(TIMEOUT)
            if not line:
                break
            lines.append(line)
        expected = set(constants.COMMANDS)
        self.assertEqual(set(lines), expected,
                         "help debe listar los comandos definidos en constants.COMMANDS")
        c.close()

    def test_quit_answers_ok(self) -> None:
        c = self.new_client()
        c.close()
        self.assertEqual(c.status, constants.CODE_OK)

    def test_lookup(self) -> None:
        for name in ("bar", "foo", "x"):
            open(os.path.join(DATADIR, name), "w").close()
        c = self.new_client()
        files = sorted(c.file_lookup())
        self.assertEqual(c.status, constants.CODE_OK)
        self.assertEqual(files, ["bar", "foo", "x"])
        c.close()

    def test_empty_file_listing(self) -> None:
        """Directorio vacío: file_lookup debe devolver [] y CODE_OK."""
        c = self.new_client()
        files = c.file_lookup()
        self.assertEqual(c.status, constants.CODE_OK)
        self.assertEqual(files, [])
        c.close()

    def test_retrieve_full_file(self) -> None:
        """retrieve() descarga un archivo completo (get_metadata + get_slice)."""
        self.output_file = "quijote.txt"
        content = "En un lugar de la Mancha..."
        with open(os.path.join(DATADIR, self.output_file), "w") as f:
            f.write(content)
        c = self.new_client()
        c.retrieve(self.output_file)
        self.assertEqual(c.status, constants.CODE_OK)
        with open(self.output_file) as f:
            self.assertEqual(f.read(), content)
        c.close()

    def test_context_manager(self) -> None:
        """El cliente se puede usar como context manager y cierra al salir."""
        open(os.path.join(DATADIR, "one"), "w").close()
        with client.Client() as c:
            files = c.file_lookup()
            self.assertEqual(c.status, constants.CODE_OK)
            self.assertIn("one", files)
        self.assertFalse(c.connected)

    def test_get_metadata(self) -> None:
        test_size = 123459
        with open(os.path.join(DATADIR, "bar"), "w") as f:
            f.write("x" * test_size)
        c = self.new_client()
        m = c.get_metadata('bar')
        self.assertEqual(c.status, constants.CODE_OK)
        self.assertEqual(m, test_size,
                         "El tamaño reportado para el archivo no es el correcto")
        c.close()

    def test_get_metadata_empty(self) -> None:
        open(os.path.join(DATADIR, "bar"), "w").close()
        c = self.new_client()
        m = c.get_metadata('bar')
        self.assertEqual(c.status, constants.CODE_OK)
        self.assertEqual(m, 0,
                         "El tamaño reportado para el archivo no es el correcto")
        c.close()

    def test_get_full_slice(self) -> None:
        self.output_file = "bar"
        test_data = "The quick brown fox jumped over the lazy dog"
        with open(os.path.join(DATADIR, self.output_file), "w") as f:
            f.write(test_data)
        c = self.new_client()
        c.get_slice(self.output_file, 0, len(test_data))
        self.assertEqual(c.status, constants.CODE_OK)
        with open(self.output_file) as f:
            self.assertEqual(f.read(), test_data,
                             "El contenido del archivo no es el correcto")
        c.close()

    def test_partial_slices(self) -> None:
        self.output_file = "bar"
        test_data = "a" * 100 + "b" * 200 + "c" * 300
        with open(os.path.join(DATADIR, self.output_file), "w") as f:
            f.write(test_data)
        c = self.new_client()
        c.get_slice(self.output_file, 0, 100)
        self.assertEqual(c.status, constants.CODE_OK)
        with open(self.output_file) as f:
            self.assertEqual(f.read(), "a" * 100,
                             "El contenido del archivo no es el correcto")
        c.get_slice(self.output_file, 100, 200)
        self.assertEqual(c.status, constants.CODE_OK)
        with open(self.output_file) as f:
            self.assertEqual(f.read(), "b" * 200,
                             "El contenido del archivo no es el correcto")
        c.get_slice(self.output_file, 200, 200)
        self.assertEqual(c.status, constants.CODE_OK)
        with open(self.output_file) as f:
            self.assertEqual(f.read(), "b" * 100 + "c" * 100,
                             "El contenido del archivo no es el correcto")
        c.get_slice(self.output_file, 500, 100)
        self.assertEqual(c.status, constants.CODE_OK)
        with open(self.output_file) as f:
            self.assertEqual(f.read(), "c" * 100,
                             "El contenido del archivo no es el correcto")
        c.close()

    def test_get_slice_raw(self) -> None:
        """get_slice ... raw devuelve bytes en bruto con Content-Length (N = SIZE)."""
        self.output_file = "rawbin"
        data = bytes(range(256))
        with open(os.path.join(DATADIR, self.output_file), "wb") as f:
            f.write(data)
        c = self.new_client()
        c.get_slice(self.output_file, 0, 256, raw=True)
        self.assertEqual(c.status, constants.CODE_OK)
        with open(self.output_file, "rb") as f:
            self.assertEqual(f.read(), data)
        c.close()

    def test_get_slice_raw_partial(self) -> None:
        self.output_file = "seg"
        with open(os.path.join(DATADIR, self.output_file), "wb") as f:
            f.write(b"abcdefghij")
        c = self.new_client()
        c.get_slice(self.output_file, 3, 4, raw=True)
        self.assertEqual(c.status, constants.CODE_OK)
        with open(self.output_file, "rb") as f:
            self.assertEqual(f.read(), b"defg")
        c.close()

    def test_get_slice_rejects_bad_raw_token(self) -> None:
        open(os.path.join(DATADIR, "bar"), "w").close()
        c = self.new_client()
        c.send("get_slice bar 0 1 rawx")
        status, _ = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.INVALID_ARGUMENTS)
        c.close()


class TestHFTPErrors(TestBase):
    """Tests de manejo de errores: EOL incorrecto, comando inválido, argumentos, archivo no encontrado."""

    def test_bad_eol(self) -> None:
        c = self.new_client()
        c.send('qui\nt\n')
        status, message = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.BAD_EOL,
                         "El servidor no contestó 100 ante un fin de línea erróneo")

    def test_bad_eol_single_lf(self) -> None:
        """Chequeo: LF sin CR dispara BAD_EOL.
        Donde: `Connection.handle` (buffer con '\n' sin '\r\n').
        Enviamos: `quit\n`.
        Esperamos: `BAD_EOL` (100) y cierre.
        Por qué: el protocolo exige CRLF exacto.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect((CONNECT_ADDR, constants.DEFAULT_PORT))
        except socket.error:
            self.fail("No se pudo establecer conexión al server")
        s.sendall(b"quit\n")
        buf = b""
        deadline = time.time() + TIMEOUT
        while b"\r\n" not in buf and time.time() < deadline:
            r, _, _ = select.select([s], [], [], max(0.01, deadline - time.time()))
            if r:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        s.close()
        self.assertIn(b"\r\n", buf, "No hubo respuesta ante LF suelto")
        line = buf.split(b"\r\n", 1)[0].decode("ascii")
        code = int(line.split(None, 1)[0])
        self.assertEqual(code, constants.BAD_EOL,
                         "El servidor no contestó 100 ante LF sin CR")

    def test_bad_command(self) -> None:
        c = self.new_client()
        c.send('verdura')
        status, message = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.INVALID_COMMAND,
                         "El servidor no contestó 200 ante un comando inválido")
        c.close()

    def test_empty_command_line_bad_request(self) -> None:
        """Línea de pedido vacía (solo \\r\\n o espacios) → 101 BAD REQUEST (error fatal)."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect((CONNECT_ADDR, constants.DEFAULT_PORT))
        except socket.error:
            self.fail("No se pudo establecer conexión al server")
        s.sendall(b"\r\n")
        buf = b""
        deadline = time.time() + TIMEOUT
        while b"\r\n" not in buf and time.time() < deadline:
            r, _, _ = select.select([s], [], [], max(0.01, deadline - time.time()))
            if r:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        s.close()
        self.assertIn(b"\r\n", buf, "No hubo respuesta ante comando vacío")
        line = buf.split(b"\r\n", 1)[0].decode("ascii")
        code = int(line.split(None, 1)[0])
        self.assertEqual(code, constants.BAD_REQUEST,
                         "El servidor no contestó 101 ante un comando vacío")

    def test_bad_argument_count(self) -> None:
        c = self.new_client()
        c.send('quit passing extra arguments!')
        status, message = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.INVALID_ARGUMENTS,
                         "El servidor no contestó 201 ante una lista de argumentos "
                         "muy larga")
        c.close()

    def test_help_with_arguments_is_invalid(self) -> None:
        """Chequeo: `help` no acepta argumentos.
        Donde: `Connection._handle_help`.
        Enviamos: `help extra`.
        Esperamos: `INVALID_ARGUMENTS` (201).
        Por qué: el protocolo define `help` sin argumentos.
        """
        c = self.new_client()
        c.send("help extra")
        status, _ = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.INVALID_ARGUMENTS)
        c.close()

    def test_bad_argument_count_2(self) -> None:
        c = self.new_client()
        c.send('get_metadata')  # Sin argumentos
        status, message = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.INVALID_ARGUMENTS,
                         "El servidor no contestó 201 ante una lista de argumentos "
                         "muy corta")
        c.close()

    def test_get_file_listing_with_arguments_is_invalid(self) -> None:
        """Chequeo: `get_file_listing` no acepta argumentos.
        Donde: `Connection._handle_get_file_listing`.
        Enviamos: `get_file_listing extra`.
        Esperamos: `INVALID_ARGUMENTS` (201).
        Por qué: el protocolo define `get_file_listing` sin argumentos.
        """
        c = self.new_client()
        c.send("get_file_listing extra")
        status, _ = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.INVALID_ARGUMENTS)
        c.close()

    def test_bad_argument_type(self) -> None:
        with open(os.path.join(DATADIR, "bar"), "w") as f:
            f.write("data")
        c = self.new_client()
        c.send('get_slice bar x x')  # Los argumentos deberían ser enteros
        status, message = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.INVALID_ARGUMENTS,
                         "El servidor no contestó 201 ante una lista de argumentos "
                         "mal tipada (status=%d)" % status)
        c.close()

    def test_invalid_filename_metadata_rejected(self) -> None:
        """Chequeo: validación de nombres en `get_metadata`.
        Donde: `Connection._handle_get_metadata`.
        Enviamos: `get_metadata ../secret`.
        Esperamos: `INVALID_ARGUMENTS` (201).
        Por qué: bloquea path traversal.
        """
        c = self.new_client()
        c.send("get_metadata ../secret")
        status, _ = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.INVALID_ARGUMENTS)
        c.close()

    def test_invalid_filename_get_slice_rejected(self) -> None:
        """Chequeo: validación de nombres en `get_slice`.
        Donde: `Connection._handle_get_slice`.
        Enviamos: `get_slice ../secret 0 1`.
        Esperamos: `INVALID_ARGUMENTS` (201).
        Por qué: bloquea path traversal.
        """
        c = self.new_client()
        c.send("get_slice ../secret 0 1")
        status, _ = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.INVALID_ARGUMENTS)
        c.close()

    def test_get_slice_negative_offset_rejected(self) -> None:
        """Chequeo: offsets negativos no permitidos.
        Donde: `Connection._handle_get_slice`.
        Enviamos: `get_slice bar -1 1` sobre archivo existente.
        Esperamos: `INVALID_ARGUMENTS` (201).
        Por qué: el protocolo no admite offsets negativos.
        """
        with open(os.path.join(DATADIR, "bar"), "w") as f:
            f.write("x")
        c = self.new_client()
        c.send("get_slice bar -1 1")
        status, _ = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.INVALID_ARGUMENTS)
        c.close()

    def test_file_not_found(self) -> None:
        c = self.new_client()
        c.send('get_metadata does_not_exist')
        status, message = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.FILE_NOT_FOUND,
                         "El servidor no contestó 202 ante un archivo inexistente")
        c.close()

    def test_file_not_found_get_slice(self) -> None:
        """get_slice sobre archivo inexistente debe devolver 202 FILE_NOT_FOUND."""
        c = self.new_client()
        c.send('get_slice does_not_exist 0 10')
        status, message = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.FILE_NOT_FOUND,
                         "El servidor no contestó 202 ante get_slice de archivo inexistente")
        c.close()

    def test_bad_offset(self) -> None:
        """get_slice con offset+size > tamaño del archivo debe devolver 203 BAD_OFFSET."""
        with open(os.path.join(DATADIR, "bar"), "w") as f:
            f.write("abc")  # 3 bytes
        c = self.new_client()
        c.send('get_slice bar 0 10')  # 0 + 10 > 3
        status, message = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.BAD_OFFSET,
                         "El servidor no contestó 203 cuando offset+size excede el tamaño")
        c.close()

    def test_internal_error_unreadable_file(self) -> None:
        """Archivo existente pero ilegible (sin permisos de lectura) → 199 INTERNAL_ERROR."""
        path = os.path.join(DATADIR, "unreadable")
        with open(path, "w") as f:
            f.write("x")
        os.chmod(path, 0o000)
        try:
            self.new_client()
            # get_metadata suele usar solo stat/getsize (puede seguir OK con chmod 0);
            # get_slice abre el archivo y debe fallar con permiso denegado → 199.
            self.client.send("get_slice unreadable 0 1")
            status, message = self.client.read_response_line(TIMEOUT)
            self.assertEqual(
                status,
                constants.INTERNAL_ERROR,
                "Se espera 199 ante fallo al leer el archivo (p. ej. PermissionError en open)",
            )
        finally:
            os.chmod(path, 0o644)

    def test_get_file_listing_directory_unreadable(self) -> None:
        """Chequeo: error de lectura del directorio compartido.
        Donde: `Connection._handle_get_file_listing`.
        Enviamos: `get_file_listing` con directorio sin permisos.
        Esperamos: `INTERNAL_ERROR` (199).
        Por qué: el servidor debe reportar fallas de filesystem.
        """
        os.chmod(DATADIR, 0o000)
        try:
            c = self.new_client()
            _ = c.file_lookup()
            self.assertEqual(c.status, constants.INTERNAL_ERROR)
            c.close()
        finally:
            os.chmod(DATADIR, 0o755)


class _FakeSocket:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)


class TestConnectionUnit(unittest.TestCase):
    """Tests directos sobre `Connection` para cubrir ramas internas."""

    def setUp(self) -> None:
        self.tmpdir = os.path.join(DATADIR, "unit")
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        os.makedirs(self.tmpdir, exist_ok=True)
        self.sock = _FakeSocket()
        self.conn = connection.Connection(self.sock, self.tmpdir)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_is_valid_filename_rejects_empty(self) -> None:
        """Chequeo: nombre vacío es inválido.
        Donde: `Connection.is_valid_filename`.
        Enviamos: "".
        Esperamos: False.
        Por qué: el protocolo exige un filename válido.
        """
        self.assertFalse(self.conn.is_valid_filename(""))

    def test_is_valid_filename_rejects_path_separator(self) -> None:
        """Chequeo: nombre con separador es inválido.
        Donde: `Connection.is_valid_filename`.
        Enviamos: "../x".
        Esperamos: False.
        Por qué: evita path traversal.
        """
        self.assertFalse(self.conn.is_valid_filename("../x"))

    def test_handle_get_slice_invalid_args(self) -> None:
        """Chequeo: argumentos inválidos en `handle_get_slice`.
        Donde: `Connection.handle_get_slice`.
        Enviamos: lista vacía.
        Esperamos: `INVALID_ARGUMENTS` (201) en la respuesta.
        Por qué: valida cantidad de argumentos.
        """
        self.conn.handle_get_slice([])
        payload = b"".join(self.sock.sent).decode("ascii")
        self.assertTrue(payload.startswith("201"))

    def test_handle_get_slice_bad_offset(self) -> None:
        """Chequeo: offset fuera de rango en `handle_get_slice`.
        Donde: `Connection.handle_get_slice`.
        Enviamos: offset+size > size del archivo.
        Esperamos: `BAD_OFFSET` (203).
        Por qué: protege límites del archivo.
        """
        path = os.path.join(self.tmpdir, "bar")
        with open(path, "wb") as f:
            f.write(b"abc")
        self.sock.sent.clear()
        self.conn.handle_get_slice(["bar", "0", "10"])
        payload = b"".join(self.sock.sent).decode("ascii")
        self.assertTrue(payload.startswith("203"))

    def test_handle_get_slice_full_behavior(self) -> None:
        """Chequeo: comportamiento completo de `handle_get_slice`.
        Donde: `Connection.handle_get_slice`.
        Enviamos: casos base64, raw, modo inválido, archivo inexistente y args inválidos.
        Esperamos: códigos 0/201/202/203 según corresponda y framing correcto.
        Por qué: valida todos los caminos principales del envío de slices.
        """
        path = os.path.join(self.tmpdir, "data")
        with open(path, "wb") as f:
            f.write(b"abcd")

        # base64 OK
        self.sock.sent.clear()
        self.conn.handle_get_slice(["data", "1", "2"])
        first = self.sock.sent[0].decode("ascii")
        second = self.sock.sent[1]
        self.assertTrue(first.startswith("0 OK"))
        self.assertEqual(second, b"YmM=\r\n")

        # raw OK
        self.sock.sent.clear()
        self.conn.handle_get_slice(["data", "1", "2", "raw"])
        first = self.sock.sent[0].decode("ascii")
        second = self.sock.sent[1]
        self.assertTrue(first.startswith("0 OK"))
        self.assertTrue(second.startswith(b"Content-Length: 2\r\n\r\n"))
        self.assertEqual(second.split(b"\r\n\r\n", 1)[1], b"bc")

        # modo inválido
        self.sock.sent.clear()
        self.conn.handle_get_slice(["data", "0", "1", "rawx"])
        payload = b"".join(self.sock.sent).decode("ascii")
        self.assertTrue(payload.startswith("201"))

        # archivo inexistente
        self.sock.sent.clear()
        self.conn.handle_get_slice(["missing", "0", "1"])
        payload = b"".join(self.sock.sent).decode("ascii")
        self.assertTrue(payload.startswith("202"))

        # args inválidos (cantidad)
        self.sock.sent.clear()
        self.conn.handle_get_slice(["only_one_arg"])
        payload = b"".join(self.sock.sent).decode("ascii")
        self.assertTrue(payload.startswith("201"))

        # args inválidos (tipo)
        self.sock.sent.clear()
        self.conn.handle_get_slice(["data", "x", "y"])
        payload = b"".join(self.sock.sent).decode("ascii")
        self.assertTrue(payload.startswith("201"))


class TestHFTPMultiClient(TestBase):
    """Varios clientes a la vez: exige que el servidor acepte y atienda conexiones concurrentes (p. ej. hilos)."""

    def test_two_concurrent_help(self) -> None:
        outcomes: list[object] = []

        def worker() -> None:
            try:
                c = client.Client()
                try:
                    c.send("help")
                    status, _ = c.read_response_line(TIMEOUT)
                    outcomes.append(status)
                    if status == constants.CODE_OK:
                        while c.read_line(TIMEOUT):
                            pass
                finally:
                    c.close()
            except Exception as exc:
                outcomes.append(exc)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=TIMEOUT * 6)
        t2.join(timeout=TIMEOUT * 6)
        self.assertFalse(t1.is_alive() or t2.is_alive(),
                         "Los clientes concurrentes no terminaron a tiempo (¿falta atender varias conexiones?)")
        self.assertEqual(len(outcomes), 2, outcomes)
        for i, o in enumerate(outcomes):
            self.assertEqual(
                o,
                constants.CODE_OK,
                "Cliente concurrente %d: se esperaba 0 OK, obtuvo %r" % (i, o),
            )

    def test_two_concurrent_file_listing(self) -> None:
        open(os.path.join(DATADIR, "c1"), "w").close()
        open(os.path.join(DATADIR, "c2"), "w").close()
        outcomes: list[object] = []

        def worker() -> None:
            try:
                c = client.Client()
                try:
                    files = sorted(c.file_lookup())
                    outcomes.append((c.status, files))
                finally:
                    c.close()
            except Exception as exc:
                outcomes.append(exc)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=TIMEOUT * 6)
        t2.join(timeout=TIMEOUT * 6)
        self.assertFalse(t1.is_alive() or t2.is_alive(),
                         "Los clientes concurrentes no terminaron a tiempo")
        self.assertEqual(len(outcomes), 2, outcomes)
        expected = ["c1", "c2"]
        for i, o in enumerate(outcomes):
            self.assertIsInstance(o, tuple, "Cliente concurrente %d falló: %r" % (i, o))
            status, files = o
            self.assertEqual(status, constants.CODE_OK, "Cliente %d status=%s" % (i, status))
            self.assertEqual(files, expected, "Cliente %d listado incorrecto" % i)


class TestHFTPHard(TestBase):
    """Tests de robustez: entrada fragmentada, muchos archivos, nombres largos, archivos grandes."""

    def test_command_in_pieces(self) -> None:
        """Verifica que el servidor acepta un comando enviado byte a byte (buffering)."""
        c = self.new_client()
        for ch in "quit\r\n":
            c.s.send(ch.encode("ascii"))
            time.sleep(0.03)  # Pequeña pausa para fragmentar sin alargar el test
        status, message = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.CODE_OK,
                         "El servidor no entendio un quit enviado de a un caracter por vez")

    def test_multiple_commands(self) -> None:
        c = self.new_client()
        l = c.s.send(
            'get_file_listing\r\nget_file_listing\r\n'.encode("ascii"))
        assert l == len(
            'get_file_listing\r\nget_file_listing\r\n'.encode("ascii"))
        status, message = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.CODE_OK,
                         "El servidor no entendio muchos mensajes correctos "
                         "enviados juntos")
        c.connected = False
        c.s.close()

    def test_big_file(self) -> None:
        """Transferencia de archivo grande en base64: verifica que no se trunca por chunks."""
        self.output_file = "bar"
        num_blocks = 16  # 16 * 128KB = 2MB, suficiente para probar sin tardar minutos
        block_size = 2**17  # 128 KB
        with open(os.path.join(DATADIR, self.output_file), "wb") as f:
            for i in range(1, num_blocks + 1):
                f.write(bytes([i]) * block_size)
        c = self.new_client()
        size = c.get_metadata(self.output_file)
        self.assertEqual(c.status, constants.CODE_OK)
        c.get_slice(self.output_file, 0, size)
        self.assertEqual(c.status, constants.CODE_OK)
        with open(self.output_file, "rb") as f:
            for i in range(1, num_blocks + 1):
                chunk = f.read(block_size)
                self.assertEqual(chunk, bytes([i]) * block_size,
                                 "El contenido del archivo no es el correcto")
        c.close()

    def test_big_filename(self) -> None:
        """Nombre de archivo muy largo: el servidor debe responder FILE_NOT_FOUND, no colgarse."""
        c = self.new_client()
        long_name_len = 8 * 1024  # 8KB, suficiente para probar sin tardar minutos
        c.send("get_metadata " + "x" * long_name_len, timeout=TIMEOUT)
        status, message = c.read_response_line(TIMEOUT)
        self.assertEqual(status, constants.FILE_NOT_FOUND,
                         "El servidor no contestó 202 ante un archivo inexistente con "
                         "nombre muy largo (status=%d)" % status)
        c.close()

    def test_data_with_nulls(self) -> None:
        self.output_file = "bar"
        test_data = "x" * 100 + "\0" * 100 + "y" * 100
        with open(os.path.join(DATADIR, self.output_file), "w") as f:
            f.write(test_data)
        c = self.new_client()
        c.get_slice(self.output_file, 0, len(test_data))
        self.assertEqual(c.status, constants.CODE_OK)
        with open(self.output_file) as f:
            self.assertEqual(f.read(), test_data,
                             "El contenido del archivo con NULs no es el correcto")
        c.close()

    def test_long_file_listing(self) -> None:
        """Listado con muchos archivos: verifica que la respuesta no se trunca."""
        num_files = 200  # Suficiente para probar sin tardar mucho
        correct_list = [f"test_file{i:04d}" for i in range(num_files)]
        for filename in correct_list:
            open(os.path.join(DATADIR, filename), "w").close()
        c = self.new_client()
        files = sorted(c.file_lookup())
        self.assertEqual(c.status, constants.CODE_OK)
        self.assertEqual(files, correct_list,
                         "La lista de archivos no es la correcta")
        c.close()


def main() -> None:
    global DATADIR
    import argparse
    parser = argparse.ArgumentParser(description="Tests del servidor HFTP")
    parser.add_argument(
        "-d", "--datadir",
        default=DATADIR,
        help="Directorio donde genera los datos; "
             "CUIDADO: CORRER LOS TESTS *BORRA* LOS DATOS EN ESTE DIRECTORIO",
    )
    args, unknown = parser.parse_known_args()
    DATADIR = args.datadir
    unittest.main(argv=sys.argv[:1] + unknown)


if __name__ == '__main__':
    main()
