import { Send } from "lucide-react";

interface FlowButtonProps {
  text?: string;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
}

export function FlowButton({
  text = "Post",
  onClick,
  disabled,
  className = "",
}: FlowButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={text}
      className={`group relative flex items-center justify-center overflow-hidden rounded-[100px] bg-gradient-to-r from-coral-light to-coral w-72 h-12 cursor-pointer transition-all duration-[600ms] ease-[cubic-bezier(0.23,1,0.32,1)] hover:rounded-[16px] active:scale-[0.96] disabled:opacity-60 disabled:cursor-not-allowed ${className}`}
    >
      {/* Centered plane icon */}
      <Send
        className="relative z-[9] w-6 h-6 stroke-white fill-white group-hover:stroke-coral group-hover:fill-coral transition-all duration-[400ms] ease-out"
      />

      {/* Hover circle */}
      <span className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-4 h-4 bg-white rounded-[50%] opacity-0 group-hover:w-[400px] group-hover:h-[400px] group-hover:opacity-100 transition-all duration-[800ms] ease-[cubic-bezier(0.19,1,0.22,1)]"></span>
    </button>
  );
}
