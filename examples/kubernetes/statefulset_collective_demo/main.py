#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
GPU collective demo using only native Kubernetes objects (StatefulSet + headless Service).

Flow:
- Connect to worker pods via stable DNS from a headless service
- Spawn GPU-bound processes on each host
- Run an allreduce to verify NCCL across the mesh
"""

import argparse
import asyncio
import logging
import os
import socket
from typing import List

import torch
import torch.distributed as dist
from monarch.actor import Actor, attach_to_workers, endpoint
from monarch.spmd import setup_torch_elastic_env_async
from monarch.tools.network import AddrType

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s %(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


class GPUCollectiveActor(Actor):
    """Actor that runs a simple GPU allreduce collective."""

    @endpoint
    async def run_allreduce(self) -> dict:
        rank = int(os.environ["RANK"])
        local_rank = int(os.environ["LOCAL_RANK"])
        world_size = int(os.environ["WORLD_SIZE"])
        device = f"cuda:{local_rank}"

        logger.info(f"Rank {rank}/{world_size}: Initializing process group on {device}")
        dist.init_process_group("nccl", rank=rank, world_size=world_size)

        try:
            gpu_name = torch.cuda.get_device_name(local_rank)
            gpu_memory = torch.cuda.get_device_properties(local_rank).total_memory

            tensor = torch.tensor([float(rank)], device=device)
            original_value = tensor.item()

            logger.info(f"Rank {rank}: Before allreduce, tensor = {original_value}")
            dist.all_reduce(tensor, op=dist.ReduceOp.SUM)
            allreduce_result = tensor.item()
            logger.info(f"Rank {rank}: After allreduce, tensor = {allreduce_result}")

            return {
                "rank": rank,
                "world_size": world_size,
                "hostname": socket.gethostname(),
                "gpu_id": local_rank,
                "gpu_name": gpu_name,
                "gpu_memory_gb": gpu_memory / (1024**3),
                "original_value": original_value,
                "allreduce_result": allreduce_result,
                "expected_sum": sum(range(world_size)),
                "success": allreduce_result == sum(range(world_size)),
            }
        finally:
            dist.destroy_process_group()


def _worker_addresses(num_hosts: int, namespace: str, service: str, port: int) -> List[str]:
    # StatefulSet pods get stable DNS: <pod>.<headless-svc>.<ns>.svc.cluster.local
    return [
        f"tcp://monarch-worker-{i}.{service}.{namespace}.svc.cluster.local:{port}"
        for i in range(num_hosts)
    ]


async def main(num_hosts: int, num_gpus_per_host: int, namespace: str, service: str, port: int) -> None:
    logger.info("=" * 60)
    logger.info("GPU Collective Demo - Native StatefulSet")
    logger.info("=" * 60)

    # Build host mesh by dialing worker pods directly (no custom CRD/gang scheduler)
    workers = _worker_addresses(num_hosts, namespace, service, port)
    host_mesh = attach_to_workers(ca="trust_all_connections", workers=workers, name="statefulset-mesh")
    proc_mesh = host_mesh.spawn_procs({"gpus": num_gpus_per_host})

    logger.info(
        f"Config: hosts={num_hosts}, gpus/host={num_gpus_per_host} (addresses={workers})"
    )

    # Set torch distributed env (MASTER_ADDR/IP pulled from mesh)
    await setup_torch_elastic_env_async(proc_mesh, use_ipaddr=AddrType.IPv4)

    actor = proc_mesh.spawn("gpu_collective_actor", GPUCollectiveActor)
    results = await actor.run_allreduce.call()

    logger.info("=" * 60)
    logger.info("RESULTS")
    logger.info("=" * 60)

    all_success = True
    hostnames = set()

    for _, result in results.flatten("rank"):
        status = "✓" if result["success"] else "✗"
        hostnames.add(result["hostname"])
        logger.info(
            f"{status} Rank {result['rank']}: GPU {result['gpu_id']} ({result['gpu_name']}) "
            f"- allreduce {result['original_value']} -> {result['allreduce_result']}"
        )
        if not result["success"]:
            all_success = False

    logger.info("=" * 60)
    if all_success and len(hostnames) == num_hosts:
        logger.info("✓ Demo PASSED: GPU collective working across all hosts!")
    else:
        logger.error("✗ Demo FAILED: Check logs above for details")

    proc_mesh.stop().get()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GPU Collective Demo (StatefulSet)")
    parser.add_argument("--num_hosts", type=int, default=2, help="Number of worker pods")
    parser.add_argument("--num_gpus_per_host", type=int, default=4, help="GPUs per pod")
    parser.add_argument("--namespace", type=str, default="monarch-tests", help="Kubernetes namespace")
    parser.add_argument("--service", type=str, default="monarch-workers", help="Headless service name")
    parser.add_argument("--port", type=int, default=26600, help="Monarch worker listen port")
    args = parser.parse_args()
    asyncio.run(
        main(
            args.num_hosts,
            args.num_gpus_per_host,
            args.namespace,
            args.service,
            args.port,
        )
    )
