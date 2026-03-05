"""Parallel node exploration for the solution tree search."""

import asyncio
import uuid
from typing import List, Dict, Set, Optional, TYPE_CHECKING
from collections import defaultdict

from rich.panel import Panel
from rich.table import Table
from rich import box

from agent.core.solution_tree import SolutionNode, SolutionJournal
from agent.utils.general import logger, console
from agent.utils.gpu_allocator import gpu_allocator

# Avoid circular imports
if TYPE_CHECKING:
    from agent.workers.base_worker import AsyncWorker


class ParallelNodeExplorer:
    """Manages parallel exploration of solution tree nodes"""
    
    def __init__(self, worker: 'AsyncWorker', max_concurrent_nodes: int = 3):
        self.worker = worker
        self.max_concurrent_nodes = max_concurrent_nodes
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.processing_nodes: Set[str] = set()
        self.semaphore = asyncio.Semaphore(max_concurrent_nodes)
        self.exploration_count = 0
        
    async def explore_nodes_parallel(self, nodes: List[SolutionNode]) -> List[SolutionNode]:
        """Process multiple nodes in parallel, especially useful for initial drafts"""
        if not nodes:
            return []
            
        self.exploration_count += 1
        
        # Initialize GPU allocator if needed
        await gpu_allocator.initialize()
        
        # Show GPU allocation status
        gpu_status = gpu_allocator.get_allocation_status()
        gpu_info_panel = Panel(
            f"Available GPUs: {gpu_status['available_gpus']}\n"
            f"Free GPUs: {gpu_status['free_gpus']}\n"
            f"Nodes to process: {len(nodes)}",
            title="🖥️ GPU Allocation Status",
            style="blue"
        )
        console.print(gpu_info_panel)
        
        # Create table for parallel processing status
        status_table = Table(title=f"🔀 Parallel Processing {len(nodes)} Nodes", box=box.ROUNDED)
        status_table.add_column("Node ID", style="cyan")
        status_table.add_column("Stage", style="magenta")
        status_table.add_column("Status", style="green")
        status_table.add_column("GPU", style="yellow")
        
        for node in nodes:
            status_table.add_row(
                node.id[:8],
                node.stage,
                "🔄 Queued",
                "TBD"
            )
        console.print(status_table)
        
        # Create tasks for parallel execution
        tasks = []
        for node in nodes:
            if node.id not in self.processing_nodes:
                self.processing_nodes.add(node.id)
                task = asyncio.create_task(
                    self._process_node_with_semaphore(node),
                    name=f"node_{node.id[:8]}"
                )
                self.active_tasks[node.id] = task
                tasks.append(task)
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results and handle exceptions
        processed_nodes = []
        for i, (node, result) in enumerate(zip(nodes, results)):
            if isinstance(result, Exception):
                logger.error(f"Error processing node {node.id[:8]}: {result}")
                node.exec_error = str(result)
                node.is_buggy = True
            else:
                processed_nodes.append(node)
            
            # Clean up
            self.processing_nodes.discard(node.id)
            self.active_tasks.pop(node.id, None)
        
        # Show completion summary with GPU allocation info
        summary_table = Table(title="Parallel Execution Summary", box=box.ROUNDED)
        summary_table.add_column("Node ID", style="cyan")
        summary_table.add_column("Status", style="green")
        summary_table.add_column("GPU Used", style="yellow")
        summary_table.add_column("Metric", style="magenta")
        
        for node in nodes:
            status = "✅ Success" if node in processed_nodes and not node.is_buggy else "❌ Failed"
            gpu_used = node.metadata.get('allocated_gpu', 'CPU') if hasattr(node, 'metadata') else 'Unknown'
            metric = f"{node.metric_value:.4f}" if node.metric_value is not None else "N/A"
            
            summary_table.add_row(
                node.id[:8],
                status,
                f"GPU {gpu_used}" if gpu_used != 'CPU' else gpu_used,
                metric
            )
        
        console.print(summary_table)
        console.print(Panel(
            f"✅ Parallel processing complete: {len(processed_nodes)}/{len(nodes)} succeeded",
            style="green"
        ))
        
        return processed_nodes
    
    async def _process_node_with_semaphore(self, node: SolutionNode) -> None:
        """Process a single node with concurrency control and GPU allocation"""
        async with self.semaphore:
            # Allocate GPU for this node
            async with gpu_allocator.allocate_gpu_for_node(node.id) as allocated_gpu:
                if allocated_gpu is not None:
                    logger.info(f"Node {node.id[:8]} running on GPU {allocated_gpu}")
                    
                    # Store GPU info in node metadata
                    if not hasattr(node, 'metadata'):
                        node.metadata = {}
                    node.metadata['allocated_gpu'] = allocated_gpu
                else:
                    logger.warning(f"Node {node.id[:8]} running on CPU (no GPU available)")
                    
                await self.worker._process_single_node_async(node)
    
    def get_parallel_candidates(self, journal: SolutionJournal, max_candidates: int = 3) -> List[SolutionNode]:
        """Identify nodes that can be processed in parallel"""
        candidates = []
        
        # 1. Find unprocessed leaf nodes (different branches)
        leaf_nodes = journal.get_leaf_nodes()
        # Fix: Check both has_executed AND is_buggy to avoid reprocessing failed nodes
        unprocessed_leaves = [n for n in leaf_nodes 
                            if not n.has_executed and not n.is_buggy 
                            and n.id not in self.processing_nodes]
        
        # Group by parent to ensure we explore different branches
        nodes_by_parent = defaultdict(list)
        for node in unprocessed_leaves:
            nodes_by_parent[node.parent_id or "root"].append(node)
        
        # Select one node from each parent (different branches)
        for parent_id, nodes in nodes_by_parent.items():
            if nodes and len(candidates) < max_candidates:
                # Prefer nodes that haven't been attempted yet
                best_node = min(nodes, key=lambda n: (n.has_executed, n.created_at))
                candidates.append(best_node)
        
        # 2. If we need more candidates, look for other unprocessed nodes
        if len(candidates) < max_candidates:
            other_nodes = [n for n in journal.nodes.values() 
                          if not n.has_executed and not n.is_buggy
                          and n.id not in [c.id for c in candidates]
                          and n.id not in self.processing_nodes]
            
            # Add draft nodes up to limit
            for node in sorted(other_nodes, key=lambda n: n.created_at)[:max_candidates - len(candidates)]:
                candidates.append(node)
        
        return candidates[:max_candidates]
    
    async def explore_initial_drafts_parallel(self, num_drafts: int = 3) -> List[SolutionNode]:
        """Create and explore multiple initial draft solutions in parallel"""
        console.print(Panel(
            f"🎯 Creating {num_drafts} initial draft solutions in parallel",
            title="Parallel Draft Generation",
            style="blue"
        ))
        
        # Create draft nodes (using "implement" stage which is what the code expects)
        draft_nodes = []
        for i in range(num_drafts):
            draft_node = SolutionNode(
                id=str(uuid.uuid4()),
                stage="implement",  # Changed from "draft" to "implement"
                parent_id=None,
                metadata={"draft_number": i + 1, "approach_hint": f"Approach #{i+1}"}
            )
            self.worker.journal.add_node(draft_node)
            draft_nodes.append(draft_node)
        
        # Process them in parallel
        processed_drafts = await self.explore_nodes_parallel(draft_nodes)
        
        # Show results
        results_table = Table(title="📊 Draft Solutions Results", box=box.SIMPLE)
        results_table.add_column("Draft #", style="cyan")
        results_table.add_column("Status", style="green")
        results_table.add_column("Metric", style="yellow")
        
        for i, node in enumerate(draft_nodes):
            status = "✅ Success" if not node.is_buggy else "❌ Failed"
            metric = f"{node.metric_value:.3f}" if node.metric_value else "N/A"
            results_table.add_row(f"#{i+1}", status, metric)
        
        console.print(results_table)
        
        return processed_drafts
    
    async def cleanup(self):
        """Cancel any remaining tasks"""
        for task in self.active_tasks.values():
            if not task.done():
                task.cancel()
        
        # Wait for cancellations to complete
        if self.active_tasks:
            await asyncio.gather(*self.active_tasks.values(), return_exceptions=True)
        
        self.active_tasks.clear()
        self.processing_nodes.clear()