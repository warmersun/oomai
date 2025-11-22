import { Button } from "@/components/ui/button";

export default function CannedMessages() {
    const handleButtonClick = (text) => {
        sendUserMessage(text);
    };

    return (
        <div className="flex flex-wrap gap-2 mt-2">
            {props.messages && props.messages.map((text, index) => (
                <Button
                    key={index}
                    variant="outline"
                    onClick={() => handleButtonClick(text)}
                    className="mb-2"
                >
                    {text}
                </Button>
            ))}
        </div>
    );
}