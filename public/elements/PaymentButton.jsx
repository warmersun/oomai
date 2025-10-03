import { Button } from "@/components/ui/button";
import { ExternalLink } from "lucide-react";

export default function PaymentButton() {
  const handlePayment = () => {
    // Construct the payment URL with the client reference ID as a query parameter
    const paymentUrl = `${props.payment_link_url}?client_reference_id=${props.client_reference_id}`;

    // Open the payment URL in a new tab
    window.open(paymentUrl, "_blank");
  };

  return (
    <div className="flex flex-col gap-2">
      <Button 
        onClick={handlePayment}
        className="flex items-center gap-2"
      >
        Pay here <ExternalLink size={16} />
      </Button>
    </div>
  );
}
