Party - vCardDAV Module
#######################

The Party - vCardDAV module provide a new report on parties and
provide a CardDAV interface over WebDAV.

The *VCard* report on parties allow to generate a vCard_ file
containing contact informations that can be re-imported in other
programs like mail clients.

The CardDAV interface is available at
``http://server_url:8080/dbname/Contacts/`` for all softwares that
support the `CardDAV protocol`_, this brings a two-way synchronisation of
contacts.


.. _vCard: http://en.wikipedia.org/wiki/Vcard
.. _CardDAV protocol: http://www.vcarddav.org/wiki
