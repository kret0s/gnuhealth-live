Purchase Shipment Cost Module
#############################

The purchase_shipment_cost module adds shipment cost to *Supplier Shipment*.

One field is added to *Carrier*:

- *Carrier Cost Allocation Method*: The method used to allocate the cost on
  each lines of the shipment.

    - *By Value*: The cost will be allocated according to the value of each
      line. (The value is: *Quantity* * *Unit Price*)

Three new fields are added to *Supplier Shipment*:

- *Carrier*: The carrier used for the shipment.
- *Cost*: The cost of the shipment.
- *Cost Currency*: The currency of the cost.

At the reception of the shipment, the unit price of each incoming moves will be
updated according to the allocation of the cost.
