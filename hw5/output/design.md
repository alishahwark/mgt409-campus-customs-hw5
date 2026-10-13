# Problem 8: Dashboard Design

## 1. Design Philosophy

I wanted the Campus Customs dashboard to feel like a professional operations tool rather than a typical AI chatbot or admin dashboard. My design draws inspiration from Apple's minimalist interfaces, Dieter Rams's "less, but better" philosophy, and Teenage Engineering's approach to functional industrial design.

The idea was to make a complex multi-agent system feel simple and intuitive. Every element should serve a purpose, and users should be able to understand what is happening without navigating through unnecessary information.

## 2. Layout and Information Hierarchy

I chose a structured layout with a navigation sidebar, central workspace, and right-side information panel.

The central workspace focuses on tickets and agent activity, while the right panel keeps financial information and pending approvals accessible.

At the top, a compact operational overview displays key metrics such as open tickets, active runs, pending approvals, and resolved tickets.

I deliberately avoided filling the dashboard with individual cards. Instead, I used whitespace, consistent alignment, and subtle dividers to separate information.

This makes the interface easier to scan and keeps attention on the most important actions.

## 3. Visual Design

I used a predominantly white and warm off-white background with black typography, subtle gray borders, and restrained orange accents.

The light palette makes the dashboard feel clean and approachable, while orange highlights important actions and active processes.

I chose a modern sans-serif font for the main interface and a monospace font for technical details such as ticket IDs, timestamps, and MCP tool names.

The design uses a consistent spacing system, minimal shadows, and small border radii to create a precise, polished appearance.

My goal was to make the interface feel like a carefully engineered product rather than a collection of decorative UI components.

## 4. Agent Visualization

The dashboard displays all five agents: Boss, Inventory, Accounting, Facilities, and Customer Service.

Rather than using cartoon avatars or chat bubbles, I represented the agents using minimal geometric modules with functional icons and status indicators.

Boss is visually emphasized as the coordinator, while the other agents are organized around it.

Each agent's status is clearly displayed, making it easy to identify who is working, waiting, completed, or blocked.

Subtle visual changes highlight active agents and delegations without distracting from the actual information.

## 5. Agent Activity and Transparency

I designed the agent activity section as a chronological event timeline rather than a chat interface.

Each event shows the agent involved, the action performed, and its timestamp. MCP tool calls and delegations are also visible.

Additional technical details, such as tool arguments and results, can be expanded when needed.

This allows users to follow the agents' decisions without overwhelming them with technical information.

The timeline is particularly important because it makes the multi-agent system transparent and helps users understand how each ticket is being handled.

## 6. Ticket Management and Resolution

The three tickets are displayed in a compact, structured list with their descriptions and current statuses.

Users can select a ticket, start the agent team, and monitor its progress.

Statuses such as Open, Running, Awaiting Approval, Resolved, and Blocked are distinguished using clear labels and restrained color indicators.

When a ticket is resolved, the dashboard displays a summary of what each participating agent contributed.

I wanted users to understand not just whether a ticket was resolved, but how the agents reached that outcome.

## 7. Cash and Human Approvals

I placed the checking balance and pending payment approvals in the right-side information panel.

The checking balance uses large, readable typography so it can be understood immediately.

When an agent proposes a payment or purchase, the dashboard displays the amount, purpose, and relevant ticket.

A human must explicitly approve or reject the proposal. Approval also requires a confirmation step before the payment is executed.

After an approved payment, the checking balance refreshes using the updated backend data.

This keeps financial decisions transparent and ensures that agents cannot independently spend money.

## 8. Interactions and Micro-Details

I focused on small interactions that make the dashboard feel responsive and intuitive.

These include subtle hover states, clear selected-ticket indicators, loading states, expandable event details, and restrained transitions between agent statuses.

Animations are used only when they communicate something meaningful, such as an agent becoming active or a payment being processed.

I avoided excessive motion, decorative effects, and unnecessary visual elements.

These details reflect Dieter Rams's emphasis on making design understandable and unobtrusive.

## 9. Responsive Design

The dashboard adapts to different screen sizes.

On desktop, the sidebar, central workspace, and financial panel remain visible together.

On smaller screens, the layout reorganizes into a more compact structure while preserving access to tickets, agent activity, and approvals.

The goal is to maintain readability and usability without simply shrinking the desktop interface.

## 10. Overall Rationale

My main objective was to make a technically complex system feel straightforward to operate.

The dashboard brings together ticket management, agent coordination, activity monitoring, and financial approvals without making the user switch between multiple tools.

Apple influenced the clarity and visual hierarchy, Dieter Rams influenced the functional minimalism, and Teenage Engineering influenced the modular layout and attention to small interaction details.

Ultimately, I wanted the dashboard to feel like software that someone would genuinely enjoy using every day: simple, precise, transparent, and efficient.