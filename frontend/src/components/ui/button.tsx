import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const button = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50 select-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-accent-strong text-white hover:bg-accent shadow-[0_1px_0_0_rgb(255_255_255/0.15)_inset]",
        secondary: "bg-surface-3 text-fg hover:bg-line-strong border border-line-strong",
        outline: "border border-line-strong bg-transparent text-fg hover:bg-surface-2",
        ghost: "text-fg-muted hover:text-fg hover:bg-surface-2",
        danger: "bg-danger/90 text-white hover:bg-danger",
        success: "bg-ok/90 text-[#04130d] hover:bg-ok",
        link: "text-accent hover:underline underline-offset-4 px-0 h-auto",
      },
      size: { sm: "h-8 px-3 text-[13px]", md: "h-9 px-4", lg: "h-11 px-6 text-[15px]", icon: "h-9 w-9", "icon-sm": "h-8 w-8" },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, loading, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp ref={ref} className={cn(button({ variant, size }), className)} disabled={disabled || loading} {...props}>
        {asChild ? children : (
          <>
            {loading && <Loader2 className="animate-spin" aria-hidden />}
            {children}
          </>
        )}
      </Comp>
    );
  },
);
Button.displayName = "Button";
