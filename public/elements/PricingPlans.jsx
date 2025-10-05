import React, { useState } from 'react';
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Check, ExternalLink } from "lucide-react";

export default function DirectPaymentPlans() {
  // Log all incoming props to see what the component receives
  
  const {
    payment_link_oom250, 
    payment_link_oom2500,
    payment_link_oom_pro_25000,
    client_reference_id
  } = props;

  const [clickedPlanId, setClickedPlanId] = useState(null);

  const plans = [
    {
      id: "250oom",
      name: "250 Credits",
      price: "$2.50",
      description: "5 interactions",
      features: ["5 interactions", "Personal use only", "Run a couple of comprehensive analysis with follow-up questions", "One-time payment, not a subscription"],
      payment_link: payment_link_oom250
    },
    {
      id: "2500oom",
      name: "2500 Credits",
      price: "$25",
      description: "500 interactions",
      features: ["500 interactions", "Personal use only", "Suffient for regular use for about a month.", "One-time payment, not a subscription"],
      payment_link: payment_link_oom2500
    },
    {
      id: "25000pro",
      name: "25000 Pro Credits",
      description: "500 interactions",
      features: ["500 interactions", "Professional use", "Use regulary", "One-time payment, not a subscription"],
      payment_link: payment_link_oom_pro_25000
    }
  ];
  
  const handlePayment = (planId, basePaymentLink) => {
    setClickedPlanId(planId);

    let finalPaymentLink = basePaymentLink;

    if (client_reference_id && typeof client_reference_id === 'string' && client_reference_id.trim() !== '') {
      finalPaymentLink = `${basePaymentLink}?client_reference_id=${encodeURIComponent(client_reference_id)}`;
    } else {
      console.log("client_reference_id is not valid or empty, not appending it.");
    }

    window.open(finalPaymentLink, "_blank");
  };

  return (
    <div className="w-full flex flex-col sm:flex-row gap-4">
      {plans.map((plan) => {
        // Log each plan object as it's being mapped, especially its payment_link
        return (
          <Card
            key={plan.id}
            className="flex-1 flex flex-col h-full"
          >
            <CardHeader>
              <CardTitle className="text-xl font-bold">{plan.name}</CardTitle>
              <div className="mt-2">
                <span className="text-3xl font-bold">{plan.price}</span>
              </div>
              <CardDescription>{plan.description}</CardDescription>
            </CardHeader>
            <CardContent className="flex-grow">
              <ul className="space-y-2">
                {plan.features.map((feature, index) => (
                  <li key={index} className="flex items-center">
                    <Check className="h-4 w-4 mr-2 text-primary" />
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
            <CardFooter>
              <Button
                className="w-full flex items-center gap-2"
                onClick={() => {
                  handlePayment(plan.id, plan.payment_link);
                }}
                disabled={clickedPlanId !== null && clickedPlanId !== plan.id}
              >
                Pay {plan.price} <ExternalLink size={16} />
              </Button>
            </CardFooter>
          </Card>
        );
      })}
    </div>
  );
}