const { ethers } = require("hardhat");

// USDC sur Polygon mainnet: 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
// USDC sur Mumbai testnet:  0xe11A86849d99F524cAC3E7A0Ec1241828e332C62
async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("Deploying with:", deployer.address);

  const network = await ethers.provider.getNetwork();
  const isMainnet = network.chainId === 137n;

  const USDC_ADDRESS = isMainnet
    ? "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    : "0xe11A86849d99F524cAC3E7A0Ec1241828e332C62";

  const ORACLE   = process.env.ORACLE_ADDRESS   || deployer.address;
  const TREASURY = process.env.TREASURY_ADDRESS || deployer.address;

  // Initial SPX price × 100 (e.g. 5250.00 = 525000)
  const INITIAL_PRICE = 525000n;

  const Market = await ethers.getContractFactory("SP500Market");
  const market = await Market.deploy(USDC_ADDRESS, ORACLE, TREASURY);
  await market.waitForDeployment();

  const addr = await market.getAddress();
  console.log("SP500Market deployed at:", addr);
  console.log("USDC:", USDC_ADDRESS);
  console.log("Oracle:", ORACLE);
  console.log("Treasury:", TREASURY);

  // Save ABI + address
  const fs = require("fs");
  const artifact = await ethers.getContractFactory("SP500Market");
  const abi = JSON.parse(artifact.interface.formatJson());

  fs.writeFileSync(
    "../frontend/src/abi/SP500Market.json",
    JSON.stringify({ address: addr, abi }, null, 2)
  );
  console.log("ABI saved to frontend/src/abi/SP500Market.json");
}

main().catch((e) => { console.error(e); process.exit(1); });
