Account Stock Continental Module
################################

The account_stock_continental module adds continental accounting model for
stock valuation.

A new configuration field for accounting is added:

- Journal Stock: The journal used for stock move.

Four new fields are added to Product and Category:

- Account Stock: The account which is used to record stock value.
- Account Stock Supplier: The counter part account for supplier stock move.
- Account Stock Customer: The counter part account for customer stock move.
- Account Stock Production: The counter part account for production stock move.
- Account Stock Lost and Found: The counter part account for lost and found
  stock move.

As usual, if the "Use Category's accounts" is checked it is the category one
that is used otherwise it is the product one.

An Account Move is created for each Stock Move done under a fiscal year with
the account stock method set and for which one Stock Location has the type
"Storage" and an the other has the type "Supplier", "Customer", "Production" or
"Lost and Found".

If the Stock Move has a "Supplier" Location as origin, then the Account Stock
of the Product is debited and the Account Stock Supplier of the Product is
credited. The amount is the Unit Price of the move or the Cost Price of the
Product if it uses the "fixed" method.
The account move is inverted if it is the destination.

If the Stock Move has a "Customer" Location as destination, then the Account
Stock of the Product is credited and the Account Stock Customer of the Product
is debited.  The amount is the current Cost Price of the Product.
The account move is inverted if it is the origin.

When the Location has the type "Production", then the Account Stock Production
is used instead of the Supplier/Customer.

When the Location has the type "Lost and Found", then the Account Stock Lost
and Found is used instead of the Supplier/Customer.
