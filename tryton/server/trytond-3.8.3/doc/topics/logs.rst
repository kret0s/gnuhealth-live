.. _topics-logs:

=====================
Logging configuration
=====================

Without any configuration, trytond writes ERROR messages to standard output.
With the verbose flag set, it writes INFO message.
And with the verbose and development flags set, it write DEBUG message.

Logs can be configured using a `configparser-format`_ file. The filename can
be specified using trytond ``logconf`` parameter.

.. _`configparser-format`: https://docs.python.org/2/library/logging.config.html#configuration-file-format

Example
=======

This example allows to write INFO messages on standard output and on a disk log
file rotated every day.

.. highlight:: ini

::

    [formatters]
    keys: simple

    [handlers]
    keys: rotate, console

    [loggers]
    keys: root

    [formatter_simple]
    format: %(asctime)s] %(levelname)s:%(name)s:%(message)s
    datefmt: %a %b %d %H:%M:%S %Y

    [handler_rotate]
    class: handlers.TimedRotatingFileHandler
    args: ('/tmp/tryton.log', 'D', 1, 30)
    formatter: simple

    [handler_console]
    class: StreamHandler
    formatter: simple
    args: (sys.stdout,)

    [logger_root]
    level: INFO
    handlers: rotate, console
